"""Exercise the real loopback HTTP interface with GDAL processing enabled."""

import base64
import hashlib
from http.client import HTTPConnection
import json
from threading import Thread
import unittest

from rasterio.io import MemoryFile

from terrain_demo.__main__ import DemoServer
from terrain_demo.model import EXAMPLE, pixel_bytes


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DemoServer(0)
        cls.addClassCleanup(cls.server.server_close)
        thread = Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join, 2)
        cls.addClassCleanup(cls.server.shutdown)

    def request(self, path, body=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            method = 'GET' if body is None else 'POST'
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def post(self, path, payload):
        status, _, body = self.request(path, json.dumps(payload), {'Content-Type': 'application/json'})
        return status, json.loads(body)

    def test_home_and_scene_are_local_with_native_preview(self):
        status, headers, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'TerrainPrep', body)
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        status, _, body = self.request('/api/scene')
        self.assertEqual(status, 200)
        scene = json.loads(body)
        self.assertEqual(scene['example'], EXAMPLE.record())
        self.assertEqual(len(base64.b64decode(scene['pixels'])), 620 * 290 * 4)

    def test_area_and_process_use_same_bounds_and_return_real_geotiff(self):
        status, area = self.post('/api/area', EXAMPLE.record())
        self.assertEqual(status, 200)
        status, processed = self.post('/api/process', EXAMPLE.record())
        self.assertEqual(status, 200)
        manifest = processed['manifest']
        preview = base64.b64decode(processed['pixels'])
        tiff = base64.b64decode(processed['geotiff'])
        self.assertEqual(area['area_m2'], manifest['aoi']['ellipsoidal_area_m2'])
        self.assertEqual(processed['grid'], manifest['output'])
        self.assertEqual(hashlib.sha256(tiff).hexdigest(), manifest['output']['geotiff_sha256'])
        with MemoryFile(tiff) as memory, memory.open() as dataset:
            self.assertEqual(preview, pixel_bytes(dataset.read(1)))

    def test_bad_payloads_and_outside_aoi_get_client_errors(self):
        cases = [[], {'west': None}, dict(EXAMPLE.record(), east=EXAMPLE.west),
                 dict(EXAMPLE.record(), east=-104), dict(EXAMPLE.record(), east=1e309)]
        for payload in cases:
            with self.subTest(payload=payload):
                status, reply = self.post('/api/process', payload)
                self.assertEqual(status, 400)
                self.assertIn('error', reply)
        status, _, _ = self.request('/api/process', '{}', {'Content-Type': 'text/plain'})
        self.assertEqual(status, 415)
        status, _, _ = self.request('/api/area', '[', {'Content-Type': 'application/json'})
        self.assertEqual(status, 400)

    def test_server_allowlist_and_cross_origin_denials(self):
        status, _, _ = self.request('/terrain_demo/model.py')
        self.assertEqual(status, 404)
        status, _, _ = self.request('/', headers={'Host': 'example.invalid'})
        self.assertEqual(status, 403)
        status, _, _ = self.request('/', headers={'Origin': 'https://example.invalid'})
        self.assertEqual(status, 403)
