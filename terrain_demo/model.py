"""WGS 84 bounds, the analytic synthetic DEM, and raster metadata."""

import base64
from dataclasses import dataclass
import hashlib
import math

import numpy as np
import pyproj


SOURCE_CRS = "EPSG:4326"
NODATA = -9999.0
SOURCE_STEP = 0.001
SOURCE_WIDTH = 620
SOURCE_HEIGHT = 290
MODEL = "synthetic-ridge-basin-v1"
BOUND_NAMES = ("west", "south", "east", "north")


@dataclass(frozen=True)
class Bounds:
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self):
        west, south, east, north = self.tuple()
        if any(type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) for value in self.tuple()):
            raise ValueError("Enter four finite longitude and latitude values.")
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            raise ValueError("Longitudes must be between −180° and 180°.")
        if not (-90 <= south <= 90 and -90 <= north <= 90):
            raise ValueError("Latitudes must be between −90° and 90°.")
        if west > east or east - west > 180:
            raise ValueError("Antimeridian crossings and spans over 180° are unsupported.")
        if south > north:
            raise ValueError("North must be greater than south.")
        if west == east or south == north:
            raise ValueError("Select an area with nonzero width and height.")

    def tuple(self):
        return self.west, self.south, self.east, self.north

    def record(self):
        return dict(zip(BOUND_NAMES, self.tuple()))

    @classmethod
    def from_corners(cls, first, second):
        lon_a, lat_a = first
        lon_b, lat_b = second
        return cls(min(lon_a, lon_b), min(lat_a, lat_b), max(lon_a, lon_b), max(lat_a, lat_b))

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict) or set(record) != set(BOUND_NAMES):
            raise ValueError("Provide west, south, east and north bounds.")
        return cls(*(record[name] for name in BOUND_NAMES))

    def area_m2(self):
        """Integrate the WGS84 ellipsoid surface between meridians and parallels."""
        ellipsoid = pyproj.CRS(SOURCE_CRS).ellipsoid
        semimajor = ellipsoid.semi_major_metre
        flattening = 1 / ellipsoid.inverse_flattening
        e2 = flattening * (2 - flattening)
        e = math.sqrt(e2)

        def primitive(latitude):
            z = math.sin(math.radians(latitude))
            return (z / (1 - e2 * z * z) + math.atanh(e * z) / e) / 2

        return (math.radians(self.east - self.west) * semimajor**2 * (1 - e2)
                * (primitive(self.north) - primitive(self.south)))


SCENE = Bounds(-106.56, 39.47, -105.94, 39.76)
EXAMPLE = Bounds(-106.498, 39.497, -106.007, 39.734)
SOURCE_AFFINE = (SOURCE_STEP, 0.0, SCENE.west, 0.0, -SOURCE_STEP, SCENE.north)


def synthetic_surface(longitude, latitude):
    """Evaluate the documented surface at points in degrees, returning metres."""
    u = 2 * (np.asarray(longitude) - SCENE.west) / (SCENE.east - SCENE.west) - 1
    v = 2 * (np.asarray(latitude) - SCENE.south) / (SCENE.north - SCENE.south) - 1
    ridge = v - 0.43 * u - 0.17 * np.sin(3.8 * u)
    massif = 1620 * np.exp(-(ridge / 0.21)**2) * np.exp(-((u - 0.12) / 1.02)**4)
    summit = 1170 * np.exp(-((u - 0.43) / 0.3)**2 - ((v - 0.46) / 0.31)**2)
    shoulder = 790 * np.exp(-((v + 0.54 * u - 0.58) / 0.21)**2 - ((u + 0.34) / 0.63)**2)
    folds = 165 * np.sin(12 * u + 4 * np.cos(3 * v)) * np.cos(9 * v - 2.5 * u)
    texture = 65 * np.sin(27 * u + 11 * v) * np.sin(17 * v - 9 * u)
    basin = ((u + 0.55) / 0.28)**2 + ((v + 0.70) / 0.24)**2
    relief = 335 + massif + summit + shoulder + folds + texture - 860 * np.exp(-1.45 * basin)
    lake = ((u - 0.51) / 0.23)**2 + ((v + 0.58) / 0.26)**2
    # Smoothstep blends the synthetic zero-elevation terrace into the surrounding relief.
    transition = np.clip((lake - 0.52) / 0.80, 0, 1)
    relief *= transition**2 * (3 - 2 * transition)
    hole = ((u + 0.62) / 0.105)**2 + ((v - 0.36) / 0.135)**2 < 1
    return np.where(hole, NODATA, relief).astype("float32")


def source_raster():
    longitude = SCENE.west + (np.arange(SOURCE_WIDTH) + 0.5) * SOURCE_STEP
    latitude = SCENE.north - (np.arange(SOURCE_HEIGHT) + 0.5) * SOURCE_STEP
    return synthetic_surface(longitude[None, :], latitude[:, None])


def validate_scene(bounds):
    if (bounds.west < SCENE.west or bounds.south < SCENE.south
            or bounds.east > SCENE.east or bounds.north > SCENE.north):
        raise ValueError("Keep all four bounds inside the synthetic DEM footprint.")


def grid_record(elevation, affine, crs):
    height, width = elevation.shape
    step_x, _, west, _, step_y, north = tuple(affine)[:6]
    extent = west, north + height * step_y, west + width * step_x, north
    return {
        "crs": crs, "width": width, "height": height,
        "resolution": [step_x, -step_y],
        "horizontal_unit": "degree" if crs == SOURCE_CRS else "m",
        "bounds": dict(zip(BOUND_NAMES, extent)),
        "affine": list(affine)[:6],
        "dtype": "float32", "nodata": NODATA,
        "elevation_unit": "m", "vertical_datum": None,
    }


def statistics(elevation):
    valid = elevation[elevation != NODATA]
    return {
        "valid_cells": int(valid.size), "nodata_cells": int(elevation.size - valid.size),
        "min_m": float(valid.min()) if valid.size else None,
        "max_m": float(valid.max()) if valid.size else None,
        "zero_cells": int(np.count_nonzero(valid == 0)),
        "negative_cells": int(np.count_nonzero(valid < 0)),
    }


def pixel_bytes(elevation):
    return elevation.astype("<f4", copy=False).tobytes(order="C")


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def preview(elevation, grid):
    """Transport the full native raster and its metadata without display downsampling."""
    return {"grid": grid, "pixels": base64.b64encode(pixel_bytes(elevation)).decode("ascii")}
