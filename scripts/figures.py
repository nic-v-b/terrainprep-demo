"""Render scientific figures from the actual source and processed arrays."""

import argparse
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', str(Path('.matplotlib').resolve()))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np

from terrain_demo.model import EXAMPLE, NODATA, SCENE, SOURCE_STEP, source_raster
from terrain_demo.terrain import process, projected_boundary


BACKGROUND = '#111a22'
PANEL = '#17232d'
WHITE = '#edf3f4'
MUTED = '#adbeca'
CYAN = '#8af0dc'
AMBER = '#edbb8e'
HOLE = '#9b87bb'
EXTERIOR = '#324759'
VALID = '#578b80'

plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'font.size': 9,
    'text.color': WHITE, 'axes.labelcolor': MUTED, 'axes.edgecolor': '#415866',
    'axes.facecolor': PANEL, 'axes.titleweight': 'semibold',
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.facecolor': BACKGROUND,
    'grid.color': '#3e515e', 'grid.linewidth': 0.6,
})


def heading(title, subtitle):
    figure = plt.figure(figsize=(12.6, 6.1))
    figure.text(0.055, 0.932, title, fontsize=24, fontweight='semibold')
    figure.text(0.057, 0.881, subtitle, fontsize=10.5, color=MUTED)
    return figure


def write(figure, output):
    figure.savefig(output, dpi=125, metadata={'Software': 'TerrainPrep'})
    plt.close(figure)


def source_figure(output):
    figure = heading('Synthetic elevation and cross-sections',
                     'WGS 84 geographic grid · 620 × 290 cells · 0.001° spacing')
    data = source_raster()
    colours = LinearSegmentedColormap.from_list('terrain', [
        (0, '#153249'), (600 / 3800, '#2d6170'), (1000 / 3800, '#427c70'),
        (1600 / 3800, '#7f9463'), (2200 / 3800, '#b39d6c'),
        (2800 / 3800, '#c9b797'), (1, '#f2e6d1'),
    ])
    colours.set_bad(HOLE)
    map_ax = figure.add_axes([0.071, 0.26, 0.425, 0.56])
    image = map_ax.imshow(
        np.ma.masked_equal(data, NODATA), cmap=colours, vmin=-600, vmax=3200,
        extent=(SCENE.west, SCENE.east, SCENE.south, SCENE.north), origin='upper', interpolation='nearest',
    )
    map_ax.set_aspect(1 / np.cos(np.deg2rad((SCENE.south + SCENE.north) / 2)))
    map_ax.set(xlabel='Longitude (°W)', ylabel='Latitude (°N)')
    map_ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f'{abs(value):.2f}'))
    map_ax.yaxis.set_major_locator(MultipleLocator(0.1))
    bar_ax = figure.add_axes([0.114, 0.142, 0.338, 0.023])
    legend = figure.colorbar(image, cax=bar_ax, orientation='horizontal', ticks=[-600, 0, 1000, 2000, 3200])
    legend.set_label('Elevation (m)')

    longitudes = SCENE.west + (np.arange(data.shape[1]) + 0.5) * SOURCE_STEP
    for index, (row, colour, label) in enumerate([(92, CYAN, 'A'), (245, AMBER, 'B')]):
        latitude = SCENE.north - (row + 0.5) * SOURCE_STEP
        profile = np.where(data[row] == NODATA, np.nan, data[row])
        map_ax.axhline(latitude, color=colour, lw=1.1, ls=(0, (4, 2)))
        map_ax.annotate(label, (SCENE.west + 0.016, latitude), xytext=(0, 5), textcoords='offset points',
                        weight='bold', color=colour, bbox={'facecolor': BACKGROUND, 'edgecolor': 'none', 'pad': 2})
        ax = figure.add_axes([0.584, 0.552 - index * 0.355, 0.37, 0.246])
        ax.set_title(f'{label}   {latitude:.4f}° N', loc='left', color=colour, pad=7)
        ax.plot(longitudes, profile, color=colour, lw=1.6)
        ax.axhline(0, color='#647d8b', lw=0.8)
        ax.set(xlim=(SCENE.west, SCENE.east), ylim=(-650, 3300), ylabel='Elevation (m)')
        ax.set_yticks([0, 1000, 2000, 3000])
        ax.grid(axis='y', alpha=0.45)
        if index == 0:
            ax.set_xticklabels([])
            ax.annotate('NoData gap', xy=(-106.442, 90), xytext=(-106.421, 1100), color='#d5c2f5',
                        arrowprops={'arrowstyle': '-', 'color': '#d5c2f5'}, fontsize=9)
        else:
            ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f'{abs(value):.2f}'))
            ax.set_xlabel('Longitude (°W)')
            ax.annotate('Below zero', xy=(-106.42, -404), xytext=(-106.407, 950), color=AMBER,
                        arrowprops={'arrowstyle': '-', 'color': AMBER}, fontsize=9, ha='center')
            ax.annotate('Zero-elevation terrace', xy=(-106.092, 0), xytext=(-106.132, 1100), color=AMBER,
                        arrowprops={'arrowstyle': '-', 'color': AMBER}, fontsize=9, ha='center')

    figure.text(0.057, 0.049, 'Purple indicates NoData. The profiles use native source cell centres.', color=MUTED)
    write(figure, output)


def grid_figure(output):
    data, transform, inside = process(EXAMPLE)
    classes = np.where(inside, np.where(data == NODATA, 2, 1), 0)
    height, width = data.shape
    west, north = transform.c, transform.f
    east, south = west + width * transform.a, north + height * transform.e
    bbox = west, east, south, north
    boundary = np.asarray(projected_boundary(EXAMPLE, samples=257)).T
    figure = heading('Output grid and NoData mask',
                     f'WGS 84 / UTM zone 13N · {width} × {height} cells · 100 m spacing')
    colourmap = ListedColormap([EXTERIOR, VALID, HOLE])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], 3)
    main_ax = figure.add_axes([0.079, 0.218, 0.47, 0.585])
    detail_ax = figure.add_axes([0.628, 0.218, 0.31, 0.585])
    for ax in (main_ax, detail_ax):
        ax.imshow(classes, cmap=colourmap, norm=norm, extent=bbox, origin='upper', interpolation='nearest')
        ax.plot(*boundary, color=CYAN, lw=1.5)
        ax.set(xlabel='Easting (km)', ylabel='Northing (km)')
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f'{value / 1000:g}'))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f'{value / 1000:g}'))
    main_ax.set_title('Full processed GeoTIFF extent', loc='left', pad=9)
    x_min, x_max = west + 3300, west + 4800
    y_min, y_max = north - 1300, north
    main_ax.add_patch(Rectangle((x_min, y_min), x_max - x_min, y_max - y_min,
                                fill=False, lw=1.2, edgecolor=AMBER))
    detail_ax.set(xlim=(x_min, x_max), ylim=(y_min, y_max))
    detail_ax.set_title('Northwest AOI edge · cell centres', loc='left', pad=9)
    for axis in (detail_ax.xaxis, detail_ax.yaxis):
        axis.set_major_locator(MultipleLocator(400))
        axis.set_minor_locator(MultipleLocator(100))
    detail_ax.grid(which='both', color=BACKGROUND, alpha=0.58)
    centre_x, centre_y = np.meshgrid(np.arange(x_min + 50, x_max, 100), np.arange(y_min + 50, y_max, 100))
    detail_ax.scatter(centre_x, centre_y, s=4, color=WHITE, alpha=0.75)
    detail_ax.plot(*boundary, color=CYAN, lw=1.55)
    for spine in detail_ax.spines.values():
        spine.set_color(AMBER)
    legend = [
        Line2D([], [], color=CYAN, label='Projected AOI'),
        Line2D([], [], marker='s', color=EXTERIOR, lw=0, label=f'Exterior NoData  {np.count_nonzero(classes == 0):,}'),
        Line2D([], [], marker='s', color=VALID, lw=0, label=f'Valid  {np.count_nonzero(classes == 1):,}'),
        Line2D([], [], marker='s', color=HOLE, lw=0, label=f'Interior NoData  {np.count_nonzero(classes == 2):,}'),
    ]
    figure.legend(handles=legend, loc='lower center', bbox_to_anchor=(0.5, 0.073),
                  frameon=False, ncol=4, fontsize=10, labelcolor=WHITE)
    figure.text(0.057, 0.04, 'Mask membership follows each cell centre inside the geographic rectangle.', color=MUTED)
    write(figure, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('artifacts/media'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source_figure(args.out / 'synthetic-profiles.png')
    grid_figure(args.out / 'output-grid.png')
    print(f'Saved scientific figures to {args.out}.')


if __name__ == '__main__':
    main()
