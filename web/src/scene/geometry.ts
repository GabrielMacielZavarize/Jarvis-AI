import { BufferGeometry, Float32BufferAttribute, RingGeometry } from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const TAU = Math.PI * 2;
const DEG = Math.PI / 180;

export function circle(radius: number, width: number, segments = 160) {
  return new RingGeometry(radius - width / 2, radius + width / 2, segments, 1);
}

/** Several arcs (degrees) merged into one geometry. */
export function arcs(radius: number, width: number, spans: [start: number, length: number][]) {
  const parts = spans.map(
    ([start, length]) =>
      new RingGeometry(radius - width / 2, radius + width / 2, Math.max(8, Math.round(length / 2)), 1, start * DEG, length * DEG),
  );
  return mergeGeometries(parts) ?? parts[0];
}

/** Evenly spaced dashes around a circle. */
export function dashes(radius: number, width: number, count: number, fill = 0.55) {
  const step = 360 / count;
  return arcs(
    radius,
    width,
    Array.from({ length: count }, (_, i) => [i * step, step * fill] as [number, number]),
  );
}

/** Radial tick marks; every `majorEvery`-th tick is longer. */
export function ticks(
  count: number,
  innerRadius: number,
  length: number,
  thickness: number,
  majorEvery = 0,
  majorLength = length * 2,
) {
  const positions: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * TAU;
    const major = majorEvery > 0 && i % majorEvery === 0;
    const outer = innerRadius + (major ? majorLength : length);
    const half = (major ? thickness * 1.6 : thickness) / 2;
    const cx = Math.cos(angle);
    const cy = Math.sin(angle);
    const px = -cy * half;
    const py = cx * half;
    const base = positions.length / 3;
    positions.push(
      cx * innerRadius + px, cy * innerRadius + py, 0,
      cx * innerRadius - px, cy * innerRadius - py, 0,
      cx * outer - px, cy * outer - py, 0,
      cx * outer + px, cy * outer + py, 0,
    );
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  return geometry;
}

/** Small triangles pointing at the centre, placed at the given angles (degrees). */
export function pointers(radius: number, size: number, angles: number[]) {
  const positions: number[] = [];
  for (const deg of angles) {
    const a = deg * DEG;
    const cx = Math.cos(a);
    const cy = Math.sin(a);
    const px = -cy;
    const py = cx;
    positions.push(
      cx * radius, cy * radius, 0,
      cx * (radius + size) + px * size * 0.6, cy * (radius + size) + py * size * 0.6, 0,
      cx * (radius + size) - px * size * 0.6, cy * (radius + size) - py * size * 0.6, 0,
    );
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  return geometry;
}
