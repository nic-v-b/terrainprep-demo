# Third-party software and methods

The dependency files request public packages from the user's package index. Candidate repository files contain independently authored application code, documentation and synthetic media. Python packages, runtime libraries, browser binaries, fonts, and datasets are installed or available separately, with notices supplied by their distributors.

| Dependency | Use | Upstream licence or notice |
| --- | --- | --- |
| NumPy | Analytic arrays, grid coordinates, statistics | [BSD 3-Clause and bundled notices](https://numpy.org/doc/stable/license.html) |
| Rasterio | GDAL virtual warp and GeoTIFF IO | [BSD 3-Clause](https://github.com/rasterio/rasterio/blob/main/LICENSE.txt) |
| GDAL | Raster reprojection and GeoTIFF encoding in Rasterio wheels | [MIT-style and component notices](https://gdal.org/en/stable/license.html) |
| pyproj | CRS metadata, PROJ transformations and reference area tests | [MIT](https://github.com/pyproj4/pyproj/blob/main/LICENSE) |
| PROJ | WGS 84 and UTM coordinate operations | [MIT](https://proj.org/en/stable/about.html#license) |
| Matplotlib | Reproducible scientific figures | [Matplotlib licence and bundled notices](https://matplotlib.org/stable/project/license.html) |
| DejaVu Sans | Rendered figure labels via Matplotlib | [DejaVu Fonts licence](https://dejavu-fonts.github.io/License.html) |
| Pillow | Encode browser frame captures and lossless WebP | [MIT-CMU](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| Playwright | Drive a locally installed browser for validation and capture | [Apache 2.0](https://github.com/microsoft/playwright-python/blob/main/LICENSE) |

## Method references

- WGS 84 ellipsoid parameters and longitude/latitude CRS definition. [EPSG:4326](https://epsg.org/crs_4326/WGS-84.html)
- UTM zone 13N CRS and standard Transverse Mercator usage. [EPSG:32613](https://epsg.org/crs_32613/WGS-84-UTM-zone-13N.html) · [PROJ UTM](https://proj.org/en/stable/operations/projections/utm.html)
- Meridional arc and Transverse Mercator equations. [Snyder, USGS Professional Paper 1395](https://pubs.usgs.gov/pp/1395/report.pdf)
- Oblate ellipsoid surface element and independent geodesic polygon area. [PROJ geodesic calculations](https://proj.org/en/stable/geodesic.html) · [Karney, Algorithms for geodesics](https://doi.org/10.1007/s00190-012-0578-z)
- Conventional raster warping, nearest-neighbour resampling and affine geotransforms. [GDAL raster warp](https://gdal.org/en/stable/programs/gdalwarp.html) · [GDAL geotransform tutorial](https://gdal.org/en/stable/tutorials/geotransforms_tut.html) · [Rasterio WarpedVRT](https://rasterio.readthedocs.io/en/stable/api/rasterio.vrt.html)
- Terrain shading based on 3 × 3 gradient estimation. [Horn, Hill shading and the reflectance map](https://doi.org/10.1109/PROC.1981.11918)
- GeoTIFF coordinate-reference and raster metadata conventions. [OGC GeoTIFF standard](https://www.ogc.org/standard/geotiff/)

The demonstration uses a mathematical surface and an independently drawn graticule. It requires no third-party elevation files, basemap tiles, icon packs or stock imagery. The bundled documentation images are rendered browser captures and plots of the synthetic model. Distribution and licensing of project-authored files remain subject to the owner's publication decision.
