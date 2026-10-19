import { describe, expect, it } from 'vitest';
import { addLatency, formatSeconds, LATENCY_WINDOW, latencyTone } from './latency';

describe('addLatency', () => {
  it('keeps the last value and the average of the recent turns', () => {
    let stats = addLatency(null, 1);
    stats = addLatency(stats, 3);
    expect(stats).toMatchObject({ last: 3, average: 2 });
  });

  it('forgets turns older than the window', () => {
    let stats = addLatency(null, 30);
    for (let index = 0; index < LATENCY_WINDOW; index++) stats = addLatency(stats, 1);
    expect(stats.samples).toHaveLength(LATENCY_WINDOW);
    expect(stats.average).toBe(1);
  });
});

describe('latencyTone', () => {
  it('splits instant, noticeable and stuck replies', () => {
    expect(latencyTone(0.9)).toBe('ok');
    expect(latencyTone(2.2)).toBe('warn');
    expect(latencyTone(4)).toBe('slow');
  });
});

describe('formatSeconds', () => {
  it('uses one decimal with a comma', () => {
    expect(formatSeconds(1.234)).toBe('1,2 s');
    expect(formatSeconds(2)).toBe('2,0 s');
  });
});
