import { describe, expect, it } from 'vitest';
import { areaPath, chartPoints, dayTimeline, fitDomain, linePath, nearestIndex } from './chart';

describe('chart geometry', () => {
  it('gives temperatures headroom and never an empty range', () => {
    expect(fitDomain([18.2, 24.6])).toEqual([17, 26]);
    expect(fitDomain([20, 20], 0)).toEqual([20, 21]);
    expect(fitDomain([])).toEqual([0, 1]);
  });

  it('spreads the points across the width, highest value on top', () => {
    const points = chartPoints([0, 50, 100], 110, 60, [0, 100], 5);
    expect(points).toEqual([
      { x: 5, y: 55 },
      { x: 55, y: 30 },
      { x: 105, y: 5 },
    ]);
    expect(linePath(points)).toBe('M5.0,55.0L55.0,30.0L105.0,5.0');
    expect(areaPath(points, 60)).toBe('M5.0,55.0L55.0,30.0L105.0,5.0L105.0,60L5.0,60Z');
  });

  it('snaps the crosshair to the nearest point', () => {
    const points = chartPoints([1, 2, 3, 4], 100, 40, [0, 4], 0);
    expect(nearestIndex(points, 0)).toBe(0);
    expect(nearestIndex(points, 40)).toBe(1);
    expect(nearestIndex(points, 99)).toBe(3);
  });
});

describe('dayTimeline', () => {
  const day = Date.UTC(2026, 9, 19);
  const at = (hours: number) => day + hours * 3_600_000;

  it('shows at least 8h to 20h and stretches for early or late events', () => {
    expect(dayTimeline([{ item: 'a', start: at(10), end: at(11) }], day)).toMatchObject({ from: 8, to: 20 });
    expect(dayTimeline([{ item: 'a', start: at(6.5), end: at(22.25) }], day)).toMatchObject({ from: 6, to: 23 });
  });

  it('puts overlapping events on separate lanes', () => {
    const { blocks } = dayTimeline(
      [
        { item: 'daily', start: at(9), end: at(10) },
        { item: 'almoço', start: at(9.5), end: at(11) },
        { item: 'review', start: at(10), end: at(11) },
      ],
      day,
    );
    expect(blocks.map((block) => [block.item, block.lane])).toEqual([
      ['daily', 0],
      ['almoço', 1],
      ['review', 0],
    ]);
    expect(blocks[0].left).toBeCloseTo(1 / 12);
    expect(blocks[0].width).toBeCloseTo(1 / 12);
  });
});
