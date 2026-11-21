"""GDAL/PROJ warp, AOI masking, and checksummed GeoTIFF export."""

import math

import numpy as np
import pyproj
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_bounds

from .model import (
    MODEL, NODATA, SOURCE_AFFINE, SOURCE_CRS, grid_record, pixel_bytes, sha256,
    source_raster, statistics, validate_scene,
)


OUTPUT_CRS = "EPSG:32613"
OUTPUT_STEP = 100
WARP_TOLERANCE = 1e-8
SOURCE_TRANSFORM = Affine(*SOURCE_AFFINE)
pyproj.network.set_network_enabled(False)


def process(bounds):
    """Warp to a fixed UTM lattice and mask pixel centres outside the WGS84 AOI."""
    validate_scene(bounds)
    with rasterio.Env(PROJ_NETWORK="OFF", GDAL_PAM_ENABLED="NO"):
        west, south, east, north = transform_bounds(
            SOURCE_CRS, OUTPUT_CRS, *bounds.tuple(), densify_pts=64
        )
        left, bottom = (math.floor(edge / OUTPUT_STEP) for edge in (west, south))
        right, top = (math.ceil(edge / OUTPUT_STEP) for edge in (east, north))
        right, top = max(left + 1, right), max(bottom + 1, top)
        transform = Affine(OUTPUT_STEP, 0, left * OUTPUT_STEP, 0, -OUTPUT_STEP, top * OUTPUT_STEP)
        source = source_raster()
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=source.shape[1], height=source.shape[0], count=1,
                             dtype="float32", crs=SOURCE_CRS, transform=SOURCE_TRANSFORM, nodata=NODATA) as dataset:
                dataset.write(source, 1)
            with memory.open() as dataset, WarpedVRT(
                dataset, crs=OUTPUT_CRS, transform=transform, width=right - left, height=top - bottom,
                nodata=NODATA, resampling=Resampling.nearest, tolerance=WARP_TOLERANCE,
            ) as warped:
                elevation = warped.read(1)

    height, width = elevation.shape
    x, y = np.meshgrid(transform.c + (np.arange(width) + 0.5) * transform.a,
                       transform.f + (np.arange(height) + 0.5) * transform.e)
    if elevation.size == 1:
        x, y = x.item(), y.item()
    inverse = pyproj.Transformer.from_crs(OUTPUT_CRS, SOURCE_CRS, always_xy=True)
    longitude, latitude = inverse.transform(x, y)
    inside = np.asarray((longitude >= bounds.west) & (longitude <= bounds.east)
                        & (latitude >= bounds.south) & (latitude <= bounds.north)).reshape(elevation.shape)
    elevation[~inside] = NODATA
    return elevation, transform, inside


def make_export(bounds):
    elevation, transform, inside = process(bounds)
    with rasterio.Env(GDAL_PAM_ENABLED="NO"), MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=elevation.shape[1], height=elevation.shape[0], count=1,
            dtype="float32", crs=OUTPUT_CRS, transform=transform, nodata=NODATA,
            compress="deflate", predictor=3,
        ) as dataset:
            dataset.write(elevation, 1)
            dataset.set_band_description(1, "Synthetic elevation")
            dataset.set_band_unit(1, "m")
            dataset.update_tags(AREA_OR_POINT="Area", DATASET=MODEL, VERTICAL_DATUM="unspecified")
        tiff = memory.read()

    stats = statistics(elevation)
    exterior = int(np.count_nonzero(~inside))
    source = source_raster()
    manifest = {
        "schema_version": 1,
        "aoi": {"crs": SOURCE_CRS, "bounds": bounds.record(), "ellipsoidal_area_m2": bounds.area_m2()},
        "source": {"model": MODEL, "synthetic": True, **grid_record(source, SOURCE_TRANSFORM, SOURCE_CRS),
                   "pixels_sha256": sha256(pixel_bytes(source))},
        "processing": {
            "resampling": "nearest", "grid_origin_m": [0, 0],
            "projected_bounds_densify_points": 64,
            "warp_tolerance_source_pixels": WARP_TOLERANCE,
            "mask": "inclusive WGS84 bounds at output pixel centres",
            "software": {"gdal": rasterio.__gdal_version__, "gdal_proj": rasterio.__proj_version__,
                         "rasterio": rasterio.__version__, "pyproj": pyproj.__version__,
                         "pyproj_proj": pyproj.proj_version_str, "numpy": np.__version__},
        },
        "output": {
            "file": "terrain.tif", "driver": "GTiff", "compression": "deflate",
            **grid_record(elevation, transform, OUTPUT_CRS),
            "statistics": {**stats, "exterior_cells": exterior,
                           "interior_nodata_cells": stats["nodata_cells"] - exterior},
            "pixels_sha256": sha256(pixel_bytes(elevation)), "geotiff_sha256": sha256(tiff),
        },
    }
    return elevation, tiff, manifest


def projected_boundary(bounds, samples=65):
    longitude = np.linspace(bounds.west, bounds.east, samples)
    latitude = np.linspace(bounds.south, bounds.north, samples)
    lons = np.concatenate([longitude, np.full(samples, bounds.east), longitude[::-1],
                           np.full(samples, bounds.west)])
    lats = np.concatenate([np.full(samples, bounds.south), latitude,
                           np.full(samples, bounds.north), latitude[::-1]])
    forward = pyproj.Transformer.from_crs(SOURCE_CRS, OUTPUT_CRS, always_xy=True)
    x, y = forward.transform(lons, lats)
    return np.column_stack([x, y]).tolist()
