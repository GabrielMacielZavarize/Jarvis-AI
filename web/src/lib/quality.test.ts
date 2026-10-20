import { describe, expect, it } from 'vitest';
import { autoStep, fixedLevel, GOOD_WINDOWS, SLOW_WINDOWS, startAuto } from './quality';

const run = (fpsList: number[], lite = false) => fpsList.reduce(autoStep, startAuto(lite));
const slow = Array(SLOW_WINDOWS).fill(30);

describe('automatic scene quality', () => {
  it('starts at what the device handles', () => {
    expect(startAuto(false).level).toBe('high');
    expect(startAuto(true).level).toBe('medium');
    expect(fixedLevel('auto', true)).toBe('medium');
    expect(fixedLevel('low', false)).toBe('low');
  });

  it('steps down only while the frame rate stays low, never below Economia', () => {
    expect(run([30]).level).toBe('high');
    expect(run([30, 60, 30]).level).toBe('high');
    expect(run(slow).level).toBe('medium');
    expect(run([...slow, ...slow, ...slow]).level).toBe('low');
  });

  it('climbs back after a long stretch of smooth frames, up to the device ceiling', () => {
    const smooth = Array(GOOD_WINDOWS).fill(60);
    expect(run([...slow, ...smooth]).level).toBe('high');
    expect(run([...slow, ...smooth.slice(1)]).level).toBe('medium');
    expect(run(smooth, true).level).toBe('medium');
  });

  it('gives up on a level that ran slow twice', () => {
    const smooth = Array(GOOD_WINDOWS).fill(60);
    expect(run([...slow, ...smooth, ...slow, ...smooth, ...smooth]).level).toBe('medium');
  });
});
