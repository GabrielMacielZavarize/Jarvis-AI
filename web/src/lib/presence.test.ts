import { describe, expect, it } from 'vitest';
import { awayFor, parsePresence, type PresenceState, presenceLabel } from './presence';

const NOW_S = 1_700_000_000;
const base: PresenceState = {
  enabled: true,
  running: true,
  state: 'present',
  since: NOW_S - 30,
  lock: false,
  away_minutes: 5,
  recognition: false,
  error: null,
};

describe('presenceLabel', () => {
  it('shows present and away with the time away', () => {
    expect(presenceLabel(base, NOW_S * 1000)).toEqual({ text: 'Presente', ok: true });
    expect(presenceLabel({ ...base, recognition: true, lock: true }, NOW_S * 1000).text).toBe(
      'Presente · reconhecido · bloqueia ao sair',
    );
    expect(presenceLabel({ ...base, state: 'away', since: NOW_S - 5 * 60 - 10 }, NOW_S * 1000)).toEqual({
      text: 'Ausente há 5 min',
      ok: false,
    });
  });

  it('explains when it is not watching', () => {
    expect(presenceLabel({ ...base, running: false, state: 'off' }, NOW_S * 1000).text).toBe('Desligada');
    expect(presenceLabel({ ...base, state: 'unknown' }, NOW_S * 1000).text).toBe('Verificando…');
    expect(presenceLabel({ ...base, error: 'A webcam está em uso.' }, NOW_S * 1000).text).toBe('A webcam está em uso.');
    expect(presenceLabel({ ...base, camera_off: true, error: 'x' }, NOW_S * 1000).text).toContain('liga a presença');
  });
});

describe('awayFor', () => {
  it('rounds down to minutes and hours', () => {
    expect(awayFor(20)).toBe('menos de 1 min');
    expect(awayFor(61)).toBe('1 min');
    expect(awayFor(3600)).toBe('1 h');
    expect(awayFor(3600 + 25 * 60)).toBe('1 h 25 min');
  });
});

describe('parsePresence', () => {
  it('accepts the server state and rejects anything else', () => {
    expect(parsePresence(base)).toEqual(base);
    expect(parsePresence({ detail: 'erro' })).toBeNull();
    expect(parsePresence(null)).toBeNull();
  });
});
