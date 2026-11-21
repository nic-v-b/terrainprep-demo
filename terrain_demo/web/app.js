'use strict';

const byId = (id) => document.getElementById(id);
const map = byId('map');
const profile = byId('profile');
const fieldNames = ['west', 'south', 'east', 'north'];
const fields = Object.fromEntries(fieldNames.map((name) => [name, byId(name)]));
const nodata = -9999;
const integers = new Intl.NumberFormat('en-US');
const decimals = new Intl.NumberFormat('en-US', {maximumFractionDigits: 1});
const palette = [
  [-600, 21, 50, 73], [0, 45, 97, 112], [400, 66, 124, 112],
  [1000, 127, 148, 99], [1600, 179, 157, 108], [2200, 201, 183, 151],
  [3200, 242, 230, 209],
];

let scene;
let result;
let view = 'source';
let validBounds;
let drag;
let revision = 0;
let areaTimer;
let processing = false;
let mapLayout;

function decode(encoded) {
  const binary = atob(encoded);
  return Uint8Array.from(binary, (byte) => byte.charCodeAt(0));
}

function unpack(payload) {
  const bytes = decode(payload.pixels);
  const {width, height} = payload.grid;
  if (bytes.length !== 4 * width * height) throw new Error('Unexpected raster size.');
  const data = new DataView(bytes.buffer);
  const values = new Float32Array(width * height);
  for (let index = 0; index < values.length; index++) {
    values[index] = data.getFloat32(index * 4, true);
  }
  return {grid: payload.grid, values, images: {}};
}

function canvasContext(canvas) {
  const {width, height} = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const pixelWidth = Math.max(1, Math.round(width * ratio));
  const pixelHeight = Math.max(1, Math.round(height * ratio));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return {ctx, width, height};
}

function parallelMetresPerDegree(latitude) {
  const radians = latitude * Math.PI / 180;
  const flattening = 1 / 298.257223563;
  const eccentricitySquared = flattening * (2 - flattening);
  return (Math.PI / 180) * 6378137 * Math.cos(radians)
    / Math.sqrt(1 - eccentricitySquared * Math.sin(radians) ** 2);
}

function shadeAt(raster, row, column, dx, dy) {
  const {width, height} = raster.grid;
  const {values} = raster;
  const center = values[row * width + column];
  const sample = (r, c) => {
    if (r < 0 || r >= height || c < 0 || c >= width) return center;
    const value = values[r * width + c];
    return value === nodata ? center : value;
  };
  const west = sample(row - 1, column - 1) + 2 * sample(row, column - 1) + sample(row + 1, column - 1);
  const east = sample(row - 1, column + 1) + 2 * sample(row, column + 1) + sample(row + 1, column + 1);
  const north = sample(row - 1, column - 1) + 2 * sample(row - 1, column) + sample(row - 1, column + 1);
  const south = sample(row + 1, column - 1) + 2 * sample(row + 1, column) + sample(row + 1, column + 1);
  const slopeX = (east - west) / (8 * dx);
  const slopeY = (north - south) / (8 * dy);
  // The light vector points northwest at 45° altitude.
  const light = (0.5 * slopeX - 0.5 * slopeY + Math.SQRT1_2) / Math.hypot(slopeX, slopeY, 1);
  return 0.55 + 0.60 * Math.max(0, light);
}

function rasterImage(raster, shaded) {
  const key = shaded ? 'shaded' : 'color';
  if (raster.images[key]) return raster.images[key];
  const {grid, values} = raster;
  const {width, height, bounds} = grid;
  const image = document.createElement('canvas');
  image.width = width;
  image.height = height;
  const ctx = image.getContext('2d');
  const pixels = ctx.createImageData(width, height);
  const geographic = grid.horizontal_unit === 'degree';
  const dy = grid.resolution[1] * (geographic ? 111034 : 1);
  for (let row = 0; row < height; row++) {
    const latitude = bounds.north - (row + 0.5) * grid.resolution[1];
    const dx = grid.resolution[0] * (geographic ? parallelMetresPerDegree(latitude) : 1);
    for (let column = 0; column < width; column++) {
      const index = row * width + column;
      const value = values[index];
      if (value === nodata) {
        const stripe = (column + row) % 8 < 2;
        pixels.data.set(stripe ? [51, 70, 88, 255] : [28, 43, 59, 255], index * 4);
        continue;
      }
      let stop = 1;
      while (stop < palette.length - 1 && value > palette[stop][0]) stop++;
      const low = palette[stop - 1];
      const high = palette[stop];
      const mix = Math.max(0, Math.min(1, (value - low[0]) / (high[0] - low[0])));
      // Subtle isolines help read slopes without changing the underlying samples.
      const contour = shaded && Math.abs(value / 125 - Math.round(value / 125)) < 0.023 && value !== 0;
      const light = (shaded ? shadeAt(raster, row, column, dx, dy) : 1) * (contour ? 0.84 : 1);
      for (let channel = 1; channel <= 3; channel++) {
        pixels.data[index * 4 + channel - 1] = (low[channel] + mix * (high[channel] - low[channel])) * light;
      }
      pixels.data[index * 4 + 3] = 255;
    }
  }
  ctx.putImageData(pixels, 0, 0);
  raster.images[key] = image;
  return image;
}

function currentRaster() {
  return view === 'source' ? scene : result?.raster;
}

function gridLines(ctx, layout, dimensions, geographic) {
  const {bounds, x, y, left, top, right, bottom} = layout;
  const {width} = dimensions;
  const xStep = geographic ? (width < 420 ? 0.2 : 0.1) : (width < 420 ? 20000 : 10000);
  const yStep = geographic ? 0.05 : 10000;
  ctx.font = '10px Consolas, monospace';
  ctx.strokeStyle = '#e6f4fe45';
  ctx.fillStyle = '#b5c8d4';
  ctx.lineWidth = 1;
  ctx.setLineDash([2, 5]);
  ctx.textAlign = 'center';
  for (let index = Math.ceil(bounds.west / xStep); index * xStep <= bounds.east; index++) {
    const value = index * xStep;
    const position = x(value);
    ctx.beginPath();
    ctx.moveTo(position, top);
    ctx.lineTo(position, bottom);
    ctx.stroke();
    ctx.fillText(geographic ? `${Math.abs(value).toFixed(2)}°W` : `${value / 1000} km E`, position, bottom + 15);
  }
  ctx.textAlign = 'right';
  for (let index = Math.ceil(bounds.south / yStep); index * yStep <= bounds.north; index++) {
    const value = index * yStep;
    const position = y(value);
    ctx.beginPath();
    ctx.moveTo(left, position);
    ctx.lineTo(right, position);
    ctx.stroke();
    ctx.fillText(geographic ? `${value.toFixed(2)}°N` : `${value / 1000} km`, left - 6, position + 3);
  }
  ctx.setLineDash([]);
  ctx.strokeStyle = '#718892';
  ctx.strokeRect(left, top, right - left, bottom - top);
}

function aoiOutline(ctx, layout) {
  const {x, y} = layout;
  ctx.beginPath();
  if (view === 'output') {
    for (const [index, [easting, northing]] of result.boundary.entries()) {
      if (index === 0) ctx.moveTo(x(easting), y(northing));
      else ctx.lineTo(x(easting), y(northing));
    }
    ctx.closePath();
  } else {
    const aoi = drag ? corners(drag.start, drag.end) : validBounds;
    if (!aoi) return;
    ctx.rect(x(aoi.west), y(aoi.north), x(aoi.east) - x(aoi.west), y(aoi.south) - y(aoi.north));
  }
  ctx.lineWidth = 4;
  ctx.strokeStyle = '#132629b0';
  ctx.stroke();
  ctx.lineWidth = 1.8;
  ctx.strokeStyle = '#8affea';
  ctx.stroke();
}

function drawMap() {
  const dimensions = canvasContext(map);
  const {ctx, width, height} = dimensions;
  const raster = currentRaster();
  if (!raster) return;
  const {bounds, horizontal_unit: unit} = raster.grid;
  const geographic = unit === 'degree';
  const spanX = bounds.east - bounds.west;
  const spanY = bounds.north - bounds.south;
  const aspect = spanX / spanY * (geographic ? Math.cos((bounds.north + bounds.south) * Math.PI / 360) : 1);
  const availableWidth = Math.max(1, width - 73);
  const availableHeight = Math.max(1, height - 44);
  const imageWidth = Math.min(availableWidth, availableHeight * aspect);
  const imageHeight = imageWidth / aspect;
  const left = 56 + (availableWidth - imageWidth) / 2;
  const top = 16 + (availableHeight - imageHeight) / 2;
  mapLayout = {
    bounds, left, top, right: left + imageWidth, bottom: top + imageHeight,
    x: (longitude) => left + imageWidth * (longitude - bounds.west) / spanX,
    y: (latitude) => top + imageHeight * (bounds.north - latitude) / spanY,
  };
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(rasterImage(raster, byId('shade').checked), left, top, imageWidth, imageHeight);
  gridLines(ctx, mapLayout, dimensions, geographic);
  aoiOutline(ctx, mapLayout);
}

function drawProfile() {
  const {ctx, width, height} = canvasContext(profile);
  const raster = currentRaster();
  if (!raster) return;
  const {grid, values} = raster;
  const columns = grid.width;
  const row = Math.floor((grid.height - 1) / 2);
  const geographic = grid.horizontal_unit === 'degree';
  const latitude = grid.bounds.north - (row + 0.5) * grid.resolution[1];
  const step = grid.resolution[0] * (geographic ? parallelMetresPerDegree(latitude) : 1);
  const left = 54;
  const right = width - 19;
  const top = 13;
  const bottom = height - 22;
  const x = (column) => columns === 1 ? (left + right) / 2 : left + column * (right - left) / (columns - 1);
  const y = (value) => bottom - (value + 600) * (bottom - top) / 3800;
  byId('profile-meta').textContent = `Row ${integers.format(row + 1)} of ${integers.format(grid.height)} · ${geographic ? 'Source DEM' : 'Processed DEM'}`;
  byId('profile-unit').textContent = geographic ? 'Eastward distance · km at row latitude' : 'Grid easting offset · km';
  ctx.font = '10px Consolas, monospace';
  ctx.textAlign = 'right';
  ctx.fillStyle = '#a4b6c0';
  for (const value of [0, 1000, 2000, 3000]) {
    ctx.strokeStyle = value === 0 ? '#54717a' : '#30414c';
    ctx.beginPath();
    ctx.moveTo(left, y(value));
    ctx.lineTo(right, y(value));
    ctx.stroke();
    ctx.fillText(`${integers.format(value)} m`, left - 6, y(value) + 3);
  }
  const ticks = Math.min(5, columns - 1);
  ctx.textAlign = 'center';
  for (let index = 0; index <= ticks; index++) {
    const column = ticks ? (columns - 1) * index / ticks : 0;
    ctx.fillText(decimals.format(column * step / 1000), x(column), bottom + 15);
  }
  ctx.beginPath();
  ctx.strokeStyle = '#82e3d3';
  ctx.lineWidth = 1.65;
  let connected = false;
  for (let column = 0; column < columns; column++) {
    const value = values[row * columns + column];
    if (value === nodata) {
      connected = false;
    } else if (connected) {
      ctx.lineTo(x(column), y(value));
    } else {
      ctx.moveTo(x(column), y(value));
      ctx.lineTo(x(column) + 0.6, y(value));
      connected = true;
    }
  }
  ctx.stroke();
}

function draw() {
  drawMap();
  drawProfile();
}

function setView(next) {
  view = next;
  const source = next === 'source';
  byId('source-view').setAttribute('aria-pressed', String(source));
  byId('output-view').setAttribute('aria-pressed', String(!source));
  byId('north-label').textContent = source ? 'N' : 'GN';
  byId('view-meta').textContent = source
    ? 'WGS 84 · EPSG:4326 · 0.001° grid'
    : `UTM 13N · EPSG:32613 · ${result.raster.grid.resolution[0]} m grid`;
  map.classList.toggle('selectable', source && Boolean(scene));
  draw();
}

function setFields(bounds) {
  for (const name of fieldNames) fields[name].value = String(bounds[name]);
}

function showError(message = '') {
  const node = byId('aoi-error');
  node.textContent = message;
  node.hidden = message === '';
}

function showResult() {
  const output = result?.manifest.output;
  const stats = output?.statistics;
  const formatHeight = (value) => value == null ? '—' : `${decimals.format(value)} m`;
  const formatBounds = (start, end) => `${integers.format(start)}–${integers.format(end)} m`;
  byId('output-status').textContent = output ? (stats.valid_cells ? 'PROCESSED' : 'ALL NODATA') : 'READY';
  byId('output-caption').textContent = output ? 'Statistics from the full exported grid.' : 'Process the AOI to inspect raster cells.';
  byId('minimum').textContent = formatHeight(stats?.min_m);
  byId('maximum').textContent = formatHeight(stats?.max_m);
  byId('dimensions').textContent = output ? `${output.width} × ${output.height}` : '—';
  byId('valid-cells').textContent = output ? integers.format(stats.valid_cells) : '—';
  byId('nodata-cells').textContent = output ? integers.format(stats.nodata_cells) : '—';
  byId('easting').textContent = output ? formatBounds(output.bounds.west, output.bounds.east) : '—';
  byId('northing').textContent = output ? formatBounds(output.bounds.south, output.bounds.north) : '—';
  for (const id of ['output-view', 'download-tiff', 'download-json']) byId(id).disabled = !output;
}

async function post(route, bounds) {
  const response = await fetch(route, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(bounds),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'The request failed.');
  return payload;
}

function runButton() {
  byId('process').disabled = !validBounds || processing;
}

function selectionChanged() {
  const ticket = ++revision;
  clearTimeout(areaTimer);
  validBounds = undefined;
  result = undefined;
  byId('area').textContent = '—';
  showError();
  showResult();
  runButton();
  setView('source');
  areaTimer = setTimeout(async () => {
    const bounds = Object.fromEntries(fieldNames.map((name) => [name, fields[name].valueAsNumber]));
    try {
      const payload = await post('/api/area', bounds);
      if (ticket !== revision) return;
      validBounds = bounds;
      const area = payload.area_m2 / 1e6;
      byId('area').textContent = area < 0.01 ? '< 0.01 km²' : `${decimals.format(area)} km²`;
      drawMap();
    } catch (error) {
      if (ticket === revision) showError(error.message);
    } finally {
      runButton();
    }
  }, 100);
}

async function runProcessing(event) {
  event.preventDefault();
  if (!validBounds || processing) return;
  const ticket = revision;
  processing = true;
  showError();
  runButton();
  byId('output-status').textContent = 'PROCESSING…';
  try {
    const payload = await post('/api/process', validBounds);
    if (ticket !== revision) return;
    result = {raster: unpack(payload), boundary: payload.boundary, manifest: payload.manifest, tiff: payload.geotiff};
    showResult();
    setView('output');
  } catch (error) {
    if (ticket === revision) {
      showResult();
      showError(error.message);
    }
  } finally {
    processing = false;
    runButton();
  }
}

function mapPoint(event, clamp) {
  const rect = map.getBoundingClientRect();
  const {left, right, top, bottom, bounds} = mapLayout;
  const x = (event.clientX - rect.left - left) / (right - left);
  const y = (event.clientY - rect.top - top) / (bottom - top);
  if (!clamp && (x < 0 || x > 1 || y < 0 || y > 1)) return null;
  return [bounds.west + Math.max(0, Math.min(1, x)) * (bounds.east - bounds.west),
    bounds.north - Math.max(0, Math.min(1, y)) * (bounds.north - bounds.south)];
}

function corners([lonA, latA], [lonB, latB]) {
  const round = (value) => Number(value.toFixed(6));
  return {west: round(Math.min(lonA, lonB)), south: round(Math.min(latA, latB)),
    east: round(Math.max(lonA, lonB)), north: round(Math.max(latA, latB))};
}

function download(data, name, type) {
  const link = document.createElement('a');
  const url = URL.createObjectURL(new Blob([data], {type}));
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function initialize() {
  try {
    const response = await fetch('/api/scene');
    if (!response.ok) throw new Error('Could not load the synthetic raster.');
    const payload = await response.json();
    scene = unpack(payload);
    scene.example = payload.example;
    setFields(scene.example);
    selectionChanged();
  } catch (error) {
    showError(error.message);
  }
}

map.addEventListener('pointerdown', (event) => {
  if (!scene || view !== 'source' || !event.isPrimary || event.button !== 0) return;
  const point = mapPoint(event, false);
  if (!point) return;
  map.setPointerCapture(event.pointerId);
  drag = {pointer: event.pointerId, start: point, end: point};
  drawMap();
});
map.addEventListener('pointermove', (event) => {
  if (drag?.pointer !== event.pointerId) return;
  drag.end = mapPoint(event, true);
  drawMap();
});
map.addEventListener('pointerup', (event) => {
  if (drag?.pointer !== event.pointerId) return;
  const bounds = corners(drag.start, mapPoint(event, true));
  drag = undefined;
  setFields(bounds);
  selectionChanged();
});
map.addEventListener('lostpointercapture', () => {
  if (!drag) return;
  drag = undefined;
  drawMap();
});

for (const field of Object.values(fields)) field.addEventListener('input', selectionChanged);
byId('reset').addEventListener('click', () => {
  if (!scene) return;
  setFields(scene.example);
  selectionChanged();
});
byId('aoi-form').addEventListener('submit', runProcessing);
byId('shade').addEventListener('change', drawMap);
byId('source-view').addEventListener('click', () => setView('source'));
byId('output-view').addEventListener('click', () => setView('output'));
byId('download-tiff').addEventListener('click', () => download(decode(result.tiff), 'terrain.tif', 'image/tiff'));
byId('download-json').addEventListener('click', () => download(`${JSON.stringify(result.manifest, null, 2)}\n`, 'provenance.json', 'application/json'));
const observer = new ResizeObserver(draw);
observer.observe(map);
observer.observe(profile);
initialize();
