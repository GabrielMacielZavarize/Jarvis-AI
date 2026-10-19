import { describe, expect, it } from 'vitest';
import { burnInOffset, parseAmbient, untilEvent } from './ambient';

const at = (iso: string) => new Date(iso).getTime();
const meeting = (start: string, end: string) => ({ title: 'Daily', start, end });

describe('parseAmbient', () => {
  it('keeps only usable weather and events', () => {
    expect(parseAmbient(null)).toEqual({ weather: null, next_event: null });
    expect(parseAmbient({ weather: { city: 'X' }, next_event: { title: 'Daily', start: 'ontem' } })).toEqual({
      weather: null,
      next_event: null,
    });
    const weather = { city: 'Criciúma', temperature: 22, code: 2, label: 'Parcialmente nublado' };
    expect(parseAmbient({ weather, next_event: null }).weather).toEqual(weather);
  });
});

describe('untilEvent', () => {
  const now = at('2026-10-19T10:00:00-03:00');

  it('says how long until the meeting', () => {
    expect(untilEvent(meeting('2026-10-19T10:25:00-03:00', '2026-10-19T11:00:00-03:00'), now)).toBe('em 25 min');
    expect(untilEvent(meeting('2026-10-19T12:10:00-03:00', '2026-10-19T13:00:00-03:00'), now)).toBe('em 2 h 10');
    expect(untilEvent(meeting('2026-10-19T13:00:00-03:00', '2026-10-19T14:00:00-03:00'), now)).toBe('em 3 h');
  });

  it('knows a meeting already running', () => {
    expect(untilEvent(meeting('2026-10-19T09:30:00-03:00', '2026-10-19T10:30:00-03:00'), now)).toBe('agora');
  });
});

describe('burnInOffset', () => {
  it('moves a few pixels each minute and stays small', () => {
    const first = burnInOffset(at('2026-10-19T10:00:00Z'));
    const next = burnInOffset(at('2026-10-19T10:01:00Z'));
    expect(first).not.toEqual(next);
    for (const offset of [first, next]) {
      expect(Math.abs(offset.x)).toBeLessThanOrEqual(10);
      expect(Math.abs(offset.y)).toBeLessThanOrEqual(8);
    }
  });
});
