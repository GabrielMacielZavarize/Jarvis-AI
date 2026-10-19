import { describe, expect, it } from 'vitest';
import { humLevels } from './reactorHum';

describe('humLevels', () => {
  it('idles low and closed, swells and opens with the voice', () => {
    const idle = humLevels(0, 1);
    const speaking = humLevels(0.6, 1);
    expect(speaking.gain).toBeGreaterThan(idle.gain);
    expect(speaking.cutoff).toBeGreaterThan(idle.cutoff);
    expect(humLevels(5, 1)).toEqual(humLevels(1, 1));
  });

  it('follows the interface volume and stays quiet', () => {
    expect(humLevels(1, 0).gain).toBe(0);
    expect(humLevels(1, 0.5).gain).toBeCloseTo(humLevels(1, 1).gain / 2);
    expect(humLevels(1, 1).gain).toBeLessThan(0.1);
  });
});
