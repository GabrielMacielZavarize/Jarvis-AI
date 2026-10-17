import { geoEquirectangular, geoPath } from 'd3-geo';
import { feature } from 'topojson-client';
import type { GeometryCollection, Topology } from 'topojson-specification';
import land110m from 'world-atlas/land-110m.json';

const DEG = Math.PI / 180;
const cache = new Map<number, Float32Array>();

/**
 * Land dots as interleaved [lon, lat] radians, sampled every `step` degrees from a
 * rasterised world map (so the per-dot test is a pixel lookup, not a polygon test).
 */
export function landDots(step = 2.4): Float32Array {
  const cached = cache.get(step);
  if (cached) return cached;

  const width = 720;
  const height = 360;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return new Float32Array();

  const topology = land110m as unknown as Topology<{ land: GeometryCollection }>;
  const land = feature(topology, topology.objects.land);
  const projection = geoEquirectangular()
    .scale(width / (2 * Math.PI))
    .translate([width / 2, height / 2]);
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  geoPath(projection, ctx)(land);
  ctx.fill();
  const pixels = ctx.getImageData(0, 0, width, height).data;

  const dots: number[] = [];
  for (let lat = -84; lat <= 84; lat += step) {
    const lonStep = step / Math.max(0.2, Math.cos(lat * DEG));
    for (let lon = -180; lon < 180; lon += lonStep) {
      const x = Math.floor(((lon + 180) / 360) * width);
      const y = Math.floor(((90 - lat) / 180) * height);
      if (pixels[(y * width + x) * 4 + 3] > 128) dots.push(lon * DEG, lat * DEG);
    }
  }
  const result = new Float32Array(dots);
  cache.set(step, result);
  return result;
}
