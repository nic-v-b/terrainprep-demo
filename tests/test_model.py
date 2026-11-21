"""Reference checks for geographic validation and the deterministic source."""

import math
import unittest

import numpy as np
from pyproj import Geod, Transformer

from terrain_demo.model import (
    Bounds, EXAMPLE, NODATA, SCENE, SOURCE_AFFINE, SOURCE_CRS,
    grid_record, source_raster, statistics, validate_scene,
)


class BoundsTests(unittest.TestCase):
    def test_bounds_round_trip_and_all_drawing_directions(self):
        self.assertEqual(Bounds.from_record(EXAMPLE.record()), EXAMPLE)
        southwest = EXAMPLE.west, EXAMPLE.south
        northeast = EXAMPLE.east, EXAMPLE.north
        northwest = EXAMPLE.west, EXAMPLE.north
        southeast = EXAMPLE.east, EXAMPLE.south
        for a, b in ((southwest, northeast), (northeast, southwest),
                     (northwest, southeast), (southeast, northwest)):
            with self.subTest(a=a, b=b):
                self.assertEqual(Bounds.from_corners(a, b), EXAMPLE)

    def test_zero_area_and_invalid_bounds(self):
        cases = [
            (-181, 0, 1, 1), (0, 0, 181, 1), (0, -91, 1, 1), (0, 0, 1, 91),
            (0, 1, 1, 0), (1, 0, 1, 1), (0, 1, 1, 1), (0, 0, float('inf'), 1),
            (0, float('nan'), 1, 1), (False, 0, 1, 1), ('0', 0, 1, 1), (10**400, 0, 1, 1),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                Bounds(*case)
        with self.assertRaises(ValueError):
            Bounds.from_record({'west': 0})
        with self.assertRaises(ValueError):
            validate_scene(Bounds(-106.57, 39.5, -106.1, 39.7))

    def test_antimeridian(self):
        for case in ((179, 0, -179, 2), (-179, 0, 179, 2)):
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, 'Antimeridian'):
                Bounds(*case)
        with self.assertRaisesRegex(ValueError, 'Antimeridian'):
            Bounds.from_corners((179, 0), (-179, 2))
        self.assertGreater(Bounds(179, 0, 180, 1).area_m2(), 0)

    def test_area_against_densified_geodesic_reference(self):
        geod = Geod(ellps='WGS84')
        # Independent geodesic-polygon area. Short segments approximate each parallel.
        for aoi in (EXAMPLE, Bounds(0, 0, 1, 1), Bounds(20, -71, 21, -70)):
            longitude = np.linspace(aoi.west, aoi.east, 4097)
            lons = np.concatenate((longitude, longitude[::-1]))
            lats = np.repeat([aoi.south, aoi.north], longitude.size)
            reference, _ = geod.polygon_area_perimeter(lons, lats)
            with self.subTest(aoi=aoi):
                self.assertAlmostEqual(aoi.area_m2(), reference, delta=0.1)

    def test_proj_axis_order_and_utm_reference(self):
        forward = Transformer.from_crs(4326, 32613, always_xy=True)
        east, north = forward.transform(-105, 0)
        self.assertAlmostEqual(east, 500000, delta=1e-6)
        self.assertAlmostEqual(north, 0, delta=1e-6)
        east, north = forward.transform(-105, 40)
        # Independently evaluate Snyder's WGS 84 meridional arc series through e^6.
        latitude = math.radians(40)
        flattening = 1 / 298.257223563
        e2 = flattening * (2 - flattening)
        e4, e6 = e2**2, e2**3
        arc = 6378137 * (
            (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * latitude
            - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * latitude)
            + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * latitude)
            - 35 * e6 / 3072 * math.sin(6 * latitude)
        )
        self.assertAlmostEqual(east, 500000, delta=1e-6)
        self.assertAlmostEqual(north, 0.9996 * arc, delta=0.002)
        inverse = Transformer.from_crs(32613, 4326, always_xy=True)
        np.testing.assert_allclose(inverse.transform(east, north), (-105, 40), atol=1e-10, rtol=0)


class SourceTests(unittest.TestCase):
    def test_source_landmarks_and_reproduction(self):
        raster = source_raster()
        np.testing.assert_array_equal(raster, source_raster())
        for row, col, expected in (
            (0, 0, 553.3802), (144, 310, 1845.6891), (245, 140, -404.1344),
            (92, 118, NODATA), (229, 470, 0),
        ):
            with self.subTest(row=row, col=col):
                self.assertAlmostEqual(float(raster[row, col]), expected, delta=1e-4)
        stats = statistics(raster)
        self.assertEqual(stats['nodata_cells'], 1999)
        self.assertEqual(stats['zero_cells'], 4388)
        self.assertEqual(stats['negative_cells'], 3981)

    def test_source_grid(self):
        metadata = grid_record(source_raster(), SOURCE_AFFINE, SOURCE_CRS)
        self.assertEqual(metadata['bounds'], SCENE.record())
        self.assertEqual(metadata['crs'], 'EPSG:4326')
        self.assertEqual((metadata['width'], metadata['height']), (620, 290))
        self.assertEqual(metadata['resolution'], [0.001, 0.001])
        self.assertEqual(metadata['nodata'], -9999)
        self.assertEqual(metadata['elevation_unit'], 'm')
        self.assertIsNone(metadata['vertical_datum'])

    def test_all_nodata_statistics(self):
        self.assertEqual(statistics(np.full((2, 3), NODATA)), {
            'valid_cells': 0, 'nodata_cells': 6, 'min_m': None, 'max_m': None,
            'zero_cells': 0, 'negative_cells': 0,
        })
