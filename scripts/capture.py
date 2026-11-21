"""Exercise the live browser workflow and capture its actual rendered frames."""

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
from threading import Thread

from PIL import Image
from playwright.sync_api import expect, sync_playwright
from rasterio.io import MemoryFile

from terrain_demo.__main__ import DemoServer
from terrain_demo.model import EXAMPLE, NODATA, pixel_bytes


def verify_downloads(page, payload):
    with page.expect_download() as tiff_event:
        page.get_by_role('button', name='GeoTIFF').click()
    with page.expect_download() as json_event:
        page.get_by_role('button', name='Provenance').click()
    tiff = tiff_event.value.path().read_bytes()
    manifest = json.loads(json_event.value.path().read_text(encoding='utf-8'))
    assert tiff_event.value.suggested_filename == 'terrain.tif'
    assert json_event.value.suggested_filename == 'provenance.json'
    assert manifest == payload['manifest']
    assert hashlib.sha256(tiff).hexdigest() == manifest['output']['geotiff_sha256']
    with MemoryFile(tiff) as memory, memory.open() as dataset:
        assert dataset.crs.to_epsg() == 32613
        assert dataset.nodata == NODATA
        assert hashlib.sha256(pixel_bytes(dataset.read(1))).hexdigest() == manifest['output']['pixels_sha256']


def process_selection(page, status='PROCESSED'):
    with page.expect_response(lambda response: response.url.endswith('/api/process')) as event:
        page.get_by_role('button', name='Process terrain').click()
    response = event.value
    assert response.ok, response.text()
    expect(page.locator('#output-status')).to_have_text(status)
    expect(page.get_by_role('button', name='Processed DEM')).to_have_attribute('aria-pressed', 'true')
    return response.json()


def record(page, url):
    page.goto(url, wait_until='networkidle')
    run = page.get_by_role('button', name='Process terrain')
    expect(run).to_be_enabled()

    # Check invalid edits and recovery before recording the clean workflow.
    page.locator('#west').fill('-180')
    expect(page.locator('#aoi-error')).to_contain_text('synthetic DEM footprint')
    expect(run).to_be_disabled()
    page.get_by_role('button', name='Reset').click()
    expect(run).to_be_enabled()
    expect(page.locator('#area')).to_contain_text('1,109.4 km²')

    first = process_selection(page)
    assert first['manifest']['aoi']['bounds'] == EXAMPLE.record()
    expect(page.locator('#dimensions')).to_have_text('427 × 270')
    expect(page.locator('#minimum')).to_have_text('-504.3 m')
    expect(page.locator('#valid-cells')).to_have_text('108,987')
    hero = page.screenshot(full_page=True)
    page.get_by_label('Hillshade').uncheck()
    expect(page.get_by_label('Hillshade')).not_to_be_checked()
    page.get_by_label('Hillshade').check()

    page.get_by_role('button', name='Reset').click()
    expect(run).to_be_enabled()
    frames = [(page.screenshot(full_page=True), 1200)]
    rect = page.locator('#map').bounding_box()
    start = rect['x'] + 0.83 * rect['width'], rect['y'] + 0.84 * rect['height']
    end = rect['x'] + 0.21 * rect['width'], rect['y'] + 0.15 * rect['height']
    page.mouse.move(*start)
    page.mouse.down()
    for step in range(1, 10):
        fraction = step / 9
        page.mouse.move(*(a + fraction * (b - a) for a, b in zip(start, end)))
        frames.append((page.screenshot(full_page=True), 90))
    page.mouse.up()
    expect(run).to_be_enabled()
    expect(page.locator('#west')).not_to_have_value(str(EXAMPLE.west))
    assert float(page.locator('#west').input_value()) < float(page.locator('#east').input_value())
    assert float(page.locator('#south').input_value()) < float(page.locator('#north').input_value())
    frames.append((page.screenshot(full_page=True), 850))

    second = process_selection(page)
    assert second['manifest']['aoi']['bounds'] != EXAMPLE.record()
    frames.append((page.screenshot(full_page=True), 1700))
    page.get_by_role('button', name='Provenance').hover()
    frames.append((page.screenshot(full_page=True), 700))
    verify_downloads(page, second)

    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.locator('#output-status')).to_have_text('PROCESSED')
    assert page.evaluate('document.documentElement.scrollWidth === window.innerWidth')
    page.get_by_role('button', name='Source DEM').click()
    expect(page.locator('#view-meta')).to_contain_text('0.001° grid')
    for field, value in {'west': '-106.444', 'south': '39.664', 'east': '-106.440', 'north': '39.670'}.items():
        page.locator(f'#{field}').fill(value)
    expect(run).to_be_enabled()
    empty = process_selection(page, 'ALL NODATA')
    assert empty['manifest']['output']['statistics']['min_m'] is None
    expect(page.locator('#minimum')).to_have_text('—')
    expect(page.get_by_role('button', name='GeoTIFF')).to_be_enabled()
    return hero, frames


def save_media(output, hero, frames):
    output.mkdir(parents=True, exist_ok=True)
    Image.open(BytesIO(hero)).save(output / 'terrainprep.webp', lossless=True, method=6)
    images = []
    for pixels, _ in frames:
        frame = Image.open(BytesIO(pixels)).convert('RGB')
        frame.thumbnail((1080, 850), Image.Resampling.LANCZOS)
        images.append(frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
    images[0].save(output / 'workflow.gif', save_all=True, append_images=images[1:],
                   duration=[duration for _, duration in frames], loop=0, optimize=True)


def save_evidence(directory, hero, frames):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'hero.png').write_bytes(hero)
    timeline = []
    for index, (pixels, duration) in enumerate(frames):
        filename = f'frame-{index:02d}.png'
        (directory / filename).write_bytes(pixels)
        timeline.append({'file': filename, 'duration_ms': duration})
    (directory / 'timeline.json').write_text(json.dumps(timeline, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=('msedge', 'chrome', 'chromium'), default='msedge')
    parser.add_argument('--out', type=Path, default=Path('artifacts/media'))
    parser.add_argument('--evidence', type=Path, help='save the original browser PNGs and animation timeline')
    args = parser.parse_args()
    with DemoServer(0) as server, sync_playwright() as playwright:
        url = f'http://127.0.0.1:{server.server_port}/'
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        external = []

        def local_only(route):
            if route.request.url.startswith(url):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        try:
            channel = None if args.browser == 'chromium' else args.browser
            browser = playwright.chromium.launch(
                channel=channel, args=['--disable-gpu', '--in-process-gpu', '--disable-background-networking'],
            )
            try:
                context = browser.new_context(viewport={'width': 1440, 'height': 1080}, accept_downloads=True)
                context.route('**/*', local_only)
                page = context.new_page()
                page_errors = []
                page.on('pageerror', lambda error: page_errors.append(str(error)))
                hero, frames = record(page, url)
                assert not page_errors, page_errors
                assert not external, 'The application requested an external resource.'
                print(f'Browser {browser.version}: AOI drag, validation, warp, preview, both downloads, '
                      'all-NoData and mobile layout passed.')
                print('Browser requested zero external resources.')
            finally:
                browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
    save_media(args.out, hero, frames)
    print(f'Saved actual browser screenshots and workflow frames to {args.out}.')
    if args.evidence:
        save_evidence(args.evidence, hero, frames)
        print(f'Saved original screenshot, animation source frames and timing to {args.evidence}.')


if __name__ == '__main__':
    main()
