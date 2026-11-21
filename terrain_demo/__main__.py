"""Run the loopback demo or reproduce its default export from the command line."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import base64
import json
from pathlib import Path

from .model import (
    Bounds, EXAMPLE, SOURCE_AFFINE, SOURCE_CRS,
    grid_record, preview, source_raster, validate_scene,
)


WEB = Path(__file__).with_name("web")
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/terrain.svg": ("terrain.svg", "image/svg+xml"),
}
SECURITY_POLICY = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"


def json_bytes(data):
    return json.dumps(data, allow_nan=False, ensure_ascii=False).encode("utf-8")


def scene_response():
    data = source_raster()
    return json_bytes({"example": EXAMPLE.record(),
                       **preview(data, grid_record(data, SOURCE_AFFINE, SOURCE_CRS))})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # All demo requests are local. Avoid retaining request paths or client details.
        pass

    def reply(self, status, content_type, content):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Security-Policy", SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def json_reply(self, status, content):
        self.reply(status, "application/json; charset=utf-8", json_bytes(content))

    def local_request(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get_all("Host") != [expected]:
            self.json_reply(403, {"error": "Use the demo's loopback URL."})
            return False
        origins = self.headers.get_all("Origin")
        if origins and origins != [f"http://{expected}"]:
            self.json_reply(403, {"error": "Cross-origin requests are disabled."})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        path = self.path.partition("?")[0]
        if path in ASSETS:
            filename, content_type = ASSETS[path]
            self.reply(200, content_type, (WEB / filename).read_bytes())
        elif path == "/api/scene":
            self.reply(200, "application/json; charset=utf-8", self.server.scene_payload)
        else:
            self.json_reply(404, {"error": "Unknown route."})

    def do_POST(self):
        if not self.local_request():
            return
        path = self.path.partition("?")[0]
        if path not in ("/api/area", "/api/process"):
            self.json_reply(404, {"error": "Unknown route."})
            return
        if self.headers.get_content_type() != "application/json":
            self.json_reply(415, {"error": "Send a JSON request body."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("The JSON body must be between 1 and 4096 bytes.")
            try:
                payload = json.loads(self.rfile.read(length))
            except (ValueError, RecursionError) as error:
                raise ValueError("The request body must contain valid JSON.") from error
            bounds = Bounds.from_record(payload)
            validate_scene(bounds)
        except ValueError as error:
            self.json_reply(400, {"error": str(error)})
            return

        if path == "/api/area":
            self.json_reply(200, {"area_m2": bounds.area_m2()})
            return
        try:
            from .terrain import make_export, projected_boundary
        except ImportError:
            self.json_reply(503, {"error": "Install the dependencies in requirements.txt to enable GDAL processing."})
            return
        data, tiff, manifest = make_export(bounds)
        self.json_reply(200, {
            **preview(data, manifest["output"]), "boundary": projected_boundary(bounds),
            "manifest": manifest, "geotiff": base64.b64encode(tiff).decode("ascii"),
        })


class DemoServer(HTTPServer):
    def __init__(self, port):
        self.scene_payload = scene_response()
        super().__init__(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="open the browser interface via a loopback server")
    serve.add_argument("--port", type=int, default=8765)
    example = commands.add_parser("example", help="export the documented example AOI")
    example.add_argument("--out", type=Path, default=Path("artifacts/example"))
    args = parser.parse_args()

    if args.command == "example":
        try:
            from .terrain import make_export
        except ImportError:
            parser.error("Install the dependencies in requirements.txt to enable GDAL processing.")
        _, tiff, manifest = make_export(EXAMPLE)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "terrain.tif").write_bytes(tiff)
        (args.out / "provenance.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        print(f"Exported {manifest['output']['width']} × {manifest['output']['height']} cells to {args.out}")
        return

    with DemoServer(args.port) as server:
        print(f"Open http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
