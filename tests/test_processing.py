"""Open the real GeoTIFF and compare its grid and individual samples."""

import base64
import hashlib
import json
import math
import unittest

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.io import MemoryFile

from terrain_demo.model import (
    Bounds, EXAMPLE, NODATA, SCENE, SOURCE_STEP, pixel_bytes, preview, source_raster,
)
from terrain_demo.terrain import make_export, process, projected_boundary


class ProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pixels, cls.tiff, cls.manifest = make_export(EXAMPLE)

    def test_export_crs_affine_extent_and_tags(self):
        with MemoryFile(self.tiff) as memory, memory.open() as dataset:
            self.assertEqual(dataset.crs.to_epsg(), 32613)
            self.assertEqual(dataset.driver, 'GTiff')
            self.assertEqual(dataset.dtypes, ('float32',))
            self.assertEqual(dataset.res, (100, 100))
            self.assertEqual(dataset.nodata, -9999)
            self.assertEqual(dataset.units, ('m',))
            self.assertEqual(dataset.descriptions, ('Synthetic elevation',))
            self.assertEqual(dataset.tags(), {
                'AREA_OR_POINT': 'Area', 'DATASET': 'synthetic-ridge-basin-v1', 'VERTICAL_DATUM': 'unspecified',
            })
            self.assertEqual((dataset.width, dataset.height), (427, 270))
            self.assertEqual(tuple(dataset.bounds), (371100, 4372400, 413800, 4399400))
            self.assertEqual(tuple(dataset.transform)[:6], (100, 0, 371100, 0, -100, 4399400))
            self.assertTrue(all(edge % 100 == 0 for edge in dataset.bounds))

    def test_projected_aoi_fits_aligned_grid(self):
        boundary = np.asarray(projected_boundary(EXAMPLE, samples=1001))
        west, south = boundary.min(axis=0)
        east, north = boundary.max(axis=0)
        expected = (math.floor(west / 100) * 100, math.floor(south / 100) * 100,
                    math.ceil(east / 100) * 100, math.ceil(north / 100) * 100)
        self.assertEqual(tuple(self.manifest['output']['bounds'].values()), expected)

    def test_exterior_centres_are_masked_and_hole_is_preserved(self):
        with MemoryFile(self.tiff) as memory, memory.open() as dataset:
            rows, cols = np.indices(self.pixels.shape)
            east, north = rasterio.transform.xy(dataset.transform, rows.ravel(), cols.ravel())
            east, north = np.reshape(east, rows.shape), np.reshape(north, rows.shape)
            inverse = Transformer.from_crs(32613, 4326, always_xy=True)
            lon, lat = inverse.transform(east, north)
            outside = ((lon < EXAMPLE.west) | (lon > EXAMPLE.east)
                       | (lat < EXAMPLE.south) | (lat > EXAMPLE.north))
            self.assertEqual(int(outside.sum()), 4397)
            self.assertTrue(np.all(self.pixels[outside] == NODATA))
            self.assertEqual(int(np.count_nonzero(self.pixels[~outside] == NODATA)), 1906)

            forward = Transformer.from_crs(4326, 32613, always_xy=True)
            def at(lon, lat):
                return self.pixels[dataset.index(*forward.transform(lon, lat))]
            self.assertEqual(at(-106.4422, 39.6672), NODATA)
            self.assertEqual(at(-106.0919, 39.5309), 0.0)
            self.assertLess(at(-106.4205, 39.5135), 0.0)
            self.assertNotEqual(at(-106.4205, 39.5135), NODATA)

    def test_nearest_samples_against_independent_inverse_mapping(self):
        elevation, transform, inside = process(EXAMPLE)
        rows, cols = np.indices(elevation.shape)
        east, north = rasterio.transform.xy(transform, rows[inside], cols[inside])
        inverse = Transformer.from_crs(32613, 4326, always_xy=True)
        lon, lat = inverse.transform(east, north)
        col = (lon - SCENE.west) / SOURCE_STEP
        row = (SCENE.north - lat) / SOURCE_STEP
        expected = source_raster()[np.floor(row).astype(int), np.floor(col).astype(int)]
        self.assertEqual(expected.size, 110893)
        np.testing.assert_array_equal(elevation[inside], expected)

    def test_small_aoi_all_nodata_and_out_of_bounds(self):
        hole = Bounds(-106.444, 39.664, -106.440, 39.670)
        elevation, tiff, record = make_export(hole)
        self.assertTrue(np.all(elevation == NODATA))
        self.assertGreater(record['output']['statistics']['interior_nodata_cells'], 0)
        self.assertIsNone(record['output']['statistics']['min_m'])
        with MemoryFile(tiff) as memory, memory.open() as dataset:
            self.assertTrue(dataset.read(1, masked=True).mask.all())
        tiny = Bounds(-106.4000001, 39.6000001, -106.4, 39.6000002)
        elevation, _, inside = process(tiny)
        self.assertGreaterEqual(elevation.size, 1)
        self.assertFalse(inside.any())
        with self.assertRaises(ValueError):
            process(Bounds(-107, 39, -106.5, 39.5))

    def test_preview_manifest_and_geotiff_pixels_are_identical(self):
        transport = preview(self.pixels, self.manifest['output'])
        decoded = base64.b64decode(transport['pixels'], validate=True)
        with MemoryFile(self.tiff) as memory, memory.open() as dataset:
            self.assertEqual(decoded, pixel_bytes(dataset.read(1)))
            self.assertEqual(transport['grid']['width'], dataset.width)
        self.assertEqual(json.loads(json.dumps(self.manifest, allow_nan=False)), self.manifest)
        output = self.manifest['output']
        self.assertEqual(self.manifest['aoi']['bounds'], EXAMPLE.record())
        self.assertAlmostEqual(self.manifest['aoi']['ellipsoidal_area_m2'], 1109443129.837, delta=0.001)
        self.assertEqual(self.manifest['processing']['software']['gdal'], rasterio.__gdal_version__)
        self.assertEqual(output['pixels_sha256'], hashlib.sha256(decoded).hexdigest())
        self.assertEqual(output['geotiff_sha256'], hashlib.sha256(self.tiff).hexdigest())
        self.assertIsNone(output['vertical_datum'])
        self.assertTrue(self.manifest['source']['synthetic'])
        self.assertEqual(self.manifest['source']['pixels_sha256'],
                         hashlib.sha256(pixel_bytes(source_raster())).hexdigest())
        self.assertEqual(output['statistics'], {
            'valid_cells': 108987, 'nodata_cells': 6303, 'min_m': float(self.pixels[self.pixels != NODATA].min()),
            'max_m': float(self.pixels[self.pixels != NODATA].max()), 'zero_cells': 4177, 'negative_cells': 3065,
            'exterior_cells': 4397, 'interior_nodata_cells': 1906,
        })

    def test_repeat_produces_identical_pixels_geotiff_and_manifest(self):
        pixels, tiff, manifest = make_export(EXAMPLE)
        np.testing.assert_array_equal(pixels, self.pixels)
        self.assertEqual(tiff, self.tiff)
        self.assertEqual(manifest, self.manifest)
