import { describe, expect, it } from 'vitest';
import { autoStep, fixedLevel, GOOD_WINDOWS, startAuto } from './quality';

const run = (fpsList: number[], lite = false) => fpsList.reduce(autoStep, startAuto(lite));

describe('automatic scene quality', () => {
  it('starts at what the device handles', () => {
    expect(startAuto(false).level).toBe('high');
    expect(startAuto(true).level).toBe('medium');
    expect(fixedLevel('auto', true)).toBe('medium');
    expect(fixedLevel('low', false)).toBe('low');
  });

  it('steps down while the frame rate stays low, never below Economia', () => {
    expect(run([30]).level).toBe('medium');
    expect(run([30, 25, 20]).level).toBe('low');
  });

  it('climbs back after a stretch of smooth frames, up to the device ceiling', () => {
    const smooth = Array(GOOD_WINDOWS).fill(60);
    expect(run([30, ...smooth]).level).toBe('high');
    expect(run([30, ...smooth.slice(1)]).level).toBe('medium');
    expect(run(smooth, true).level).toBe('medium');
  });

  it('gives up on a level that ran slow twice', () => {
    const smooth = Array(GOOD_WINDOWS).fill(60);
    expect(run([30, ...smooth, 30, ...smooth, ...smooth]).level).toBe('medium');
  });
});
