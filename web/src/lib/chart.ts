/** Geometry of the small charts inside the HUD cards (pixel coordinates, no chart library). */

export interface Point {
  x: number;
  y: number;
}

/** Temperatures get a little headroom; percentages use a fixed 0–100. */
export function fitDomain(values: number[], pad = 1): [number, number] {
  if (values.length === 0) return [0, 1];
  const low = Math.floor(Math.min(...values) - pad);
  const high = Math.ceil(Math.max(...values) + pad);
  return high > low ? [low, high] : [low, low + 1];
}

/** One point per value across the whole width; `inset` keeps the 2px line and the end dot inside. */
export function chartPoints(values: number[], width: number, height: number, domain: [number, number], inset = 5): Point[] {
  const [low, high] = domain;
  const span = high - low || 1;
  const step = values.length > 1 ? (width - inset * 2) / (values.length - 1) : 0;
  return values.map((value, index) => ({
    x: inset + index * step,
    y: inset + (1 - (Math.min(high, Math.max(low, value)) - low) / span) * (height - inset * 2),
  }));
}

export function linePath(points: Point[]): string {
  return points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join('');
}

/** The line closed down to the baseline, for the 10% wash under it. */
export function areaPath(points: Point[], height: number): string {
  if (points.length === 0) return '';
  const first = points[0];
  const last = points[points.length - 1];
  return `${linePath(points)}L${last.x.toFixed(1)},${height}L${first.x.toFixed(1)},${height}Z`;
}

/** Index of the data point nearest to the pointer's x (the crosshair snaps to it). */
export function nearestIndex(points: Point[], x: number): number {
  let best = 0;
  for (let index = 1; index < points.length; index++) {
    if (Math.abs(points[index].x - x) < Math.abs(points[best].x - x)) best = index;
  }
  return best;
}

export interface TimelineBlock<T> {
  item: T;
  /** 0–1 along the visible hours. */
  left: number;
  width: number;
  /** Row, so overlapping events sit one under the other. */
  lane: number;
}

/**
 * Day timeline of the agenda: hours shown (at least 8h–20h, stretched to fit the events) and each
 * timed event placed on the first lane where it does not overlap.
 */
export function dayTimeline<T>(
  items: { item: T; start: number; end: number }[],
  dayStart: number,
): { from: number; to: number; blocks: TimelineBlock<T>[] } {
  const hour = 3_600_000;
  const startHours = items.map((entry) => Math.floor((entry.start - dayStart) / hour));
  const endHours = items.map((entry) => Math.ceil((entry.end - dayStart) / hour));
  const from = Math.max(0, Math.min(8, ...startHours));
  const to = Math.min(24, Math.max(20, ...endHours));
  const span = (to - from) * hour;
  const laneEnds: number[] = [];
  const blocks = [...items]
    .sort((a, b) => a.start - b.start)
    .map((entry) => {
      let lane = laneEnds.findIndex((end) => end <= entry.start);
      if (lane < 0) lane = laneEnds.push(0) - 1;
      laneEnds[lane] = entry.end;
      const left = Math.max(0, (entry.start - dayStart - from * hour) / span);
      const right = Math.min(1, (entry.end - dayStart - from * hour) / span);
      return { item: entry.item, left, width: Math.max(0.012, right - left), lane };
    });
  return { from, to, blocks };
}
