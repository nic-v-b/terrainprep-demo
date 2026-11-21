# Scientific validation and reproduction

## Coordinate and raster methods

The AOI is defined by `(west, south, east, north)` in WGS 84 degrees. A drag in any direction normalizes to minima and maxima. A numeric form submission preserves the chosen west/east and south/north semantics and rejects invalid order. The source footprint is `−106.56°` to `−105.94°` longitude and `39.47°` to `39.76°` latitude.

WGS 84 rectangle area is the integral of `a²(1 − e²) cos(φ) / (1 − e² sin²(φ))²` over geodetic latitude `φ` and longitude, in radians. `a` and `e` are the ellipsoid's semimajor axis and eccentricity. The implementation substitutes `z = sin(φ)` and evaluates a closed-form antiderivative. The reference test instead supplies densely spaced vertices along each parallel to PROJ's geodesic polygon area calculation. Their agreement is checked within 0.1 m² on three rectangles. The UTM test checks the central meridian and equator, a published-series meridional arc calculation at 40° N, and an inverse round trip.

The source evaluates Gaussian ridges, a summit and shoulder, sinusoidal folds, and a Gaussian basin at fixed 0.001° cell centres. Normalized model coordinates `u` and `v` run from −1 to 1 across the longitude and latitude bounds. A smoothstep transition imposes an exact-zero ellipse in the southeast. The NoData ellipse is centred at `(u, v) = (−0.62, 0.36)` with semiaxes `0.105` and `0.135`. The implementation contains every coefficient. There is no random state or downloaded terrain. [Source model](../terrain_demo/model.py)

GDAL estimates the transformed AOI envelope with 64 additional samples per edge and snaps it outward on the fixed UTM lattice. A GDAL warped VRT reads nearest source cells with a transformer tolerance of `1e−8` source pixels. Inverse projection with pyproj classifies each output centre against the inclusive geographic rectangle. Exterior cells and source NoData use the same Float32 sentinel. The GeoTIFF sets the horizontal CRS, affine transform, the band unit `m`, and pixel-is-area semantics. The vertical datum field is `null` in JSON and `unspecified` in the TIFF metadata.

The browser decodes little-endian Float32 cells from the loopback API. The colour ramp has fixed elevation stops for comparing views. Optional Horn-style hillshade uses northwest illumination at 45° altitude and substitutes the centre height for missing neighbours. For the source render, east–west spacing follows the latitude parallel and north–south spacing uses a local metre approximation. The profile is a row of actual cells and skips NoData. Along the source row its x-axis follows the ellipsoid parallel. Along the processed row it reports offset in projected easting.

## Executed checks

Phase 5 used 64-bit CPython 3.12.10 on Windows with `PROJ_NETWORK=OFF`. Successful dependency imports included NumPy 2.2.6, Rasterio 1.4.4 with GDAL 3.10.3 and PROJ 9.6.0, pyproj 3.7.1 with PROJ 9.5.1, Matplotlib 3.10.9, Pillow 13.0.0, and Playwright 1.56.0. All 19 automated tests passed. Two default CLI exports produced byte-identical GeoTIFFs and provenance manifests. The reopened raster matched the documented geometry and NoData counts, and all three hashes matched the references below.

| Check | Result |
| --- | --- |
| Bounds, reverse drawing, degenerate and non-finite values, antimeridian limitations, reference area, and UTM references | 5 passed |
| Source landmarks, negative and exact zero cells, source metadata, all-NoData statistics | 3 passed |
| GeoTIFF CRS, affine, projected footprint, nearest values, interior/exterior NoData, malformed AOIs, preview equality, manifest checksums, repeatability | 7 passed |
| Live loopback HTTP source and processing routes, GeoTIFF transport, bad requests, and request allowlist | 4 passed |
| Python compile check and JavaScript syntax check | Passed |
| Edge 157.0.4341.60 browser smoke and screenshot capture | Passed with zero external application requests |
| CLI export, decoded raster readback and second export byte comparison | Passed |

The default grid contains 115,290 cells. The repository test computes the source-cell indices separately from GDAL's nearest-neighbour warp and found exact Float32 agreement at all 110,893 in-AOI centres, including 1,906 interior NoData values. It shares the generated source array, the production AOI mask, and the pyproj inverse transform used by that mask. The 4,397 exterior pixels are all NoData.

An independent audit separately inverted a Transverse Mercator series without PROJ, classified each output centre against the geographic bounds, and sampled the same synthetic source array. It compared all 115,290 expected values with the reopened GeoTIFF and found zero mismatches. The audit and repository comparisons cover the default synthetic AOI and its fixed CRS pair. A separate all-NoData GeoTIFF can be reopened and has null elevation extrema in its manifest.

The initial direct headless Chrome and Edge screenshot attempts failed when the GPU process could not start in the Windows sandbox. The final graphical checks and assets used Playwright with Edge and in-process software rendering. Cross-platform execution and current upstream vulnerability advisories were outside the local checks.

## Example checksums

The JSON manifest contains SHA-256 hashes of source pixels, processed pixels, and the GeoTIFF. Pixel hashes cover row-major little-endian Float32 values including NoData. The GeoTIFF hash covers the complete TIFF file. With the recorded dependency builds, repeat runs produced identical manifests, TIFF bytes and decoded pixels. Platform math libraries and TIFF compressors can affect byte equality across environments.

```text
source pixels  bb84323cd74d81207612263f833395d4f66972745b87adc5da72a9e486c3a29b
output pixels  2d343788c178a699c78251378cb5f5182181bf256f82734079618cd712ed71fc
GeoTIFF        b0478f4b8519e75e62b16031d0652345a0d8bd32d271ec5372e2c8b502b5506b
```

## Regenerate portfolio assets

Use the Python 3.12 virtual environment described in the README. The media requirements pin Pillow 13.0.0, which fixes the GIF-comment issue tracked as CVE-2026-112891 and requires Python 3.11 or later. Phase 5 regenerated both scientific figures and captured the workflow with Edge 157.0.4341.60 and Playwright 1.56.0. The browser run made zero external application requests. Pillow 13.0.0 reopened the generated WebP and decoded all 13 GIF frames. Verification outputs were saved separately from the included media, which was produced with the earlier setup. The capture script manages its own loopback server and uses installed Edge by default. `--browser chrome` selects installed Chrome. With a Playwright-managed Chromium browser already installed, use `--browser chromium`.

```text
python -m pip install -r requirements-media.txt
python -m scripts.figures
python -m scripts.capture
```

The commands write to the ignored `artifacts/media/` directory. Use `--out docs/media` to regenerate the candidate README assets. Add `--evidence artifacts/capture-evidence` to the capture command to keep the original PNG screenshot, 13 animation frames, and frame timings. The capture script reopens the downloaded GeoTIFF, compares it with the downloaded provenance, verifies UI validation and mobile layout, and blocks any non-loopback application request before saving the genuine frames.
