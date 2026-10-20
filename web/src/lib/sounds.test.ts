import { describe, expect, it } from 'vitest';
import {
  clampVolume,
  CueLimiter,
  cueForHudEvent,
  DEFAULT_SOUND_SETTINGS,
  loadSoundSettings,
  parseSoundSettings,
  saveSoundSettings,
  SOUND_CUES,
  SOUND_STORAGE_KEY,
  styledTone,
} from './sounds';
import { themeInfo } from './themes';
import type { HudEvent } from './types';

const tool = (name: string, status: 'running' | 'done' | 'error'): HudEvent => ({ type: 'tool', name, status, ts: 1 });

class MemoryStorage {
  data = new Map<string, string>();
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.data.set(key, value);
  }
}

describe('cueForHudEvent', () => {
  it('maps tool events to start, finish and error sounds', () => {
    expect(cueForHudEvent(tool('get_weather', 'running'))).toBe('toolStart');
    expect(cueForHudEvent(tool('get_weather', 'done'))).toBe('toolDone');
    expect(cueForHudEvent(tool('get_weather', 'error'))).toBe('error');
  });

  it('plays the confirmation sound for spoken-code confirmations', () => {
    expect(cueForHudEvent(tool('confirm_email_send', 'done'))).toBe('confirm');
    expect(cueForHudEvent(tool('confirm_app_install', 'done'))).toBe('confirm');
    expect(cueForHudEvent(tool('confirm_screen_action', 'error'))).toBe('error');
  });

  it('leaves the goodbye to the link closing sound', () => {
    expect(cueForHudEvent(tool('end_session', 'running'))).toBeNull();
    expect(cueForHudEvent(tool('end_session', 'done'))).toBeNull();
  });

  it('rings when a timer finishes, not while it runs', () => {
    const timer = (status: 'running' | 'done') =>
      ({ type: 'card', kind: 'timer', data: { id: 't1', label: 'Café', duration_s: 60, status }, ts: 1 }) as HudEvent;
    expect(cueForHudEvent(timer('done'))).toBe('timerDone');
    expect(cueForHudEvent(timer('running'))).toBeNull();
    expect(cueForHudEvent({ type: 'voice', state: 'speaking', ts: 1 })).toBeNull();
  });
});

describe('sound settings', () => {
  it('defaults to on at a moderate volume', () => {
    expect(parseSoundSettings(null)).toEqual(DEFAULT_SOUND_SETTINGS);
    expect(DEFAULT_SOUND_SETTINGS.enabled).toBe(true);
    expect(parseSoundSettings('{broken')).toEqual(DEFAULT_SOUND_SETTINGS);
  });

  it('keeps valid values and clamps the volume', () => {
    expect(parseSoundSettings('{"enabled":false,"volume":0.3}')).toEqual({ enabled: false, volume: 0.3 });
    expect(parseSoundSettings('{"volume":7}')).toEqual({ enabled: true, volume: 1 });
    expect(parseSoundSettings('{"enabled":"yes","volume":-2}')).toEqual({ enabled: true, volume: 0 });
    expect(clampVolume('abc')).toBe(DEFAULT_SOUND_SETTINGS.volume);
    expect(clampVolume(0.25)).toBe(0.25);
  });

  it('survives a reload through the browser storage', () => {
    const storage = new MemoryStorage();
    saveSoundSettings({ enabled: false, volume: 0.45 }, storage);
    expect(JSON.parse(storage.getItem(SOUND_STORAGE_KEY)!)).toEqual({ enabled: false, volume: 0.45 });
    expect(loadSoundSettings(storage)).toEqual({ enabled: false, volume: 0.45 });
  });

  it('works without storage or with blocked storage', () => {
    expect(loadSoundSettings(null)).toEqual(DEFAULT_SOUND_SETTINGS);
    const blocked = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    expect(loadSoundSettings(blocked)).toEqual(DEFAULT_SOUND_SETTINGS);
    expect(() => saveSoundSettings(DEFAULT_SOUND_SETTINGS, blocked)).not.toThrow();
  });
});

describe('CueLimiter', () => {
  it('drops the same cue repeated within a few milliseconds', () => {
    const limiter = new CueLimiter();
    expect(limiter.allow('toolStart', 1000)).toBe(true);
    expect(limiter.allow('toolStart', 1050)).toBe(false);
    expect(limiter.allow('toolDone', 1050)).toBe(true);
    expect(limiter.allow('toolStart', 1200)).toBe(true);
  });

  it('plays one closing sound when the wake word closes the link', () => {
    const limiter = new CueLimiter();
    expect(limiter.allow('sleep', 1000)).toBe(true);
    expect(limiter.allow('linkClose', 1400)).toBe(false);
    expect(limiter.allow('linkClose', 5000)).toBe(true);
  });

  it('still plays the link opening right after the wake chime', () => {
    const limiter = new CueLimiter();
    expect(limiter.allow('wake', 1000)).toBe(true);
    expect(limiter.allow('linkOpen', 1001)).toBe(true);
  });
});

describe('SOUND_CUES', () => {
  it('has short, quiet, audible tones for every cue', () => {
    for (const [cue, tones] of Object.entries(SOUND_CUES)) {
      expect(tones.length, cue).toBeGreaterThan(0);
      for (const spec of tones) {
        expect(spec.gain, cue).toBeGreaterThan(0);
        expect(spec.gain, cue).toBeLessThanOrEqual(0.2);
        expect(spec.at + spec.duration, cue).toBeLessThan(1);
        expect(Math.min(spec.from, spec.to), cue).toBeGreaterThanOrEqual(100);
      }
    }
  });
});

describe('styledTone', () => {
  it('plays each cue in the protocol timbre', () => {
    const spec = SOUND_CUES.linkOpen[1];
    expect(styledTone(spec, themeInfo('jarvis').sound)).toEqual({ ...spec, wave: 'sine' });
    const mark3 = styledTone(spec, themeInfo('mark3').sound);
    expect(mark3.from).toBeLessThan(spec.from);
    expect(mark3.wave).toBe('triangle');
    // A tone that asks for its own oscillator keeps it (the error buzz stays square).
    expect(styledTone(SOUND_CUES.error[0], themeInfo('mark3').sound).wave).toBe('square');
    expect(styledTone(spec, themeInfo('stealth').sound).gain).toBeLessThan(spec.gain);
  });
});
