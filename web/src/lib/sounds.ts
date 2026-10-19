/**
 * VOZ-30: interface sounds synthesized with Web Audio (no audio files): link opening/closing,
 * tool start/finish, confirmation, error and timer done. Volume and on/off live in the Sistema
 * panel and are saved in this browser.
 */
import type { HudEvent } from './types';

export type SoundCue =
  | 'wake'
  | 'sleep'
  | 'linkOpen'
  | 'linkClose'
  | 'toolStart'
  | 'toolDone'
  | 'confirm'
  | 'error'
  | 'timerDone';

export interface Tone {
  /** Seconds after the cue starts. */
  at: number;
  from: number;
  to: number;
  duration: number;
  gain: number;
  wave?: OscillatorType;
}

/** Short, quiet tones in the HUD's register: rising = something opens/works, falling = it ends. */
export const SOUND_CUES: Record<SoundCue, Tone[]> = {
  wake: [
    { at: 0, from: 660, to: 990, duration: 0.09, gain: 0.16 },
    { at: 0.1, from: 990, to: 1480, duration: 0.14, gain: 0.14 },
  ],
  sleep: [
    { at: 0, from: 990, to: 660, duration: 0.12, gain: 0.1 },
    { at: 0.13, from: 660, to: 440, duration: 0.18, gain: 0.08 },
  ],
  linkOpen: [
    { at: 0, from: 220, to: 440, duration: 0.32, gain: 0.07, wave: 'triangle' },
    { at: 0.08, from: 880, to: 1320, duration: 0.12, gain: 0.08 },
    { at: 0.2, from: 1320, to: 1760, duration: 0.16, gain: 0.06 },
  ],
  linkClose: [
    { at: 0, from: 1320, to: 880, duration: 0.14, gain: 0.07 },
    { at: 0.12, from: 440, to: 180, duration: 0.34, gain: 0.07, wave: 'triangle' },
  ],
  toolStart: [{ at: 0, from: 1180, to: 1560, duration: 0.05, gain: 0.05 }],
  toolDone: [
    { at: 0, from: 1560, to: 1560, duration: 0.05, gain: 0.05 },
    { at: 0.06, from: 2090, to: 2090, duration: 0.07, gain: 0.04 },
  ],
  confirm: [
    { at: 0, from: 880, to: 880, duration: 0.08, gain: 0.09 },
    { at: 0.09, from: 1175, to: 1175, duration: 0.08, gain: 0.09 },
    { at: 0.18, from: 1760, to: 1760, duration: 0.2, gain: 0.08 },
  ],
  error: [
    { at: 0, from: 330, to: 300, duration: 0.14, gain: 0.08, wave: 'square' },
    { at: 0.17, from: 260, to: 220, duration: 0.22, gain: 0.08, wave: 'square' },
  ],
  timerDone: [
    { at: 0, from: 1320, to: 1320, duration: 0.12, gain: 0.12 },
    { at: 0.18, from: 1320, to: 1320, duration: 0.12, gain: 0.12 },
    { at: 0.36, from: 1760, to: 1760, duration: 0.3, gain: 0.12 },
  ],
};

export interface SoundSettings {
  enabled: boolean;
  /** 0..1, on top of each tone's own gain. */
  volume: number;
}

export const DEFAULT_SOUND_SETTINGS: SoundSettings = { enabled: true, volume: 0.6 };
export const SOUND_STORAGE_KEY = 'jarvis.sounds';

type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>;

export function clampVolume(value: unknown): number {
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return DEFAULT_SOUND_SETTINGS.volume;
  return Math.min(1, Math.max(0, number));
}

export function parseSoundSettings(raw: string | null): SoundSettings {
  if (!raw) return { ...DEFAULT_SOUND_SETTINGS };
  try {
    const data = JSON.parse(raw) as Partial<SoundSettings>;
    return {
      enabled: typeof data.enabled === 'boolean' ? data.enabled : DEFAULT_SOUND_SETTINGS.enabled,
      volume: data.volume === undefined ? DEFAULT_SOUND_SETTINGS.volume : clampVolume(data.volume),
    };
  } catch {
    return { ...DEFAULT_SOUND_SETTINGS };
  }
}

function browserStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadSoundSettings(storage: Storage | null = browserStorage()): SoundSettings {
  try {
    return parseSoundSettings(storage?.getItem(SOUND_STORAGE_KEY) ?? null);
  } catch {
    return { ...DEFAULT_SOUND_SETTINGS };
  }
}

export function saveSoundSettings(settings: SoundSettings, storage: Storage | null = browserStorage()) {
  try {
    storage?.setItem(SOUND_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Storage blocked: the choice simply won't survive a reload.
  }
}

/** Cues that would stack (the wake word's closing chime and the link closing) share a group. */
const CUE_GROUP: Partial<Record<SoundCue, string>> = { sleep: 'close', linkClose: 'close', wake: 'open', linkOpen: 'open' };
const CUE_GAP_MS: Record<string, number> = { close: 1500, open: 0 };
const DEFAULT_GAP_MS = 90;

/** Skips a cue repeated too fast (several tools in a row) or one already covered by its group. */
export class CueLimiter {
  private last = new Map<string, number>();

  allow(cue: SoundCue, now: number): boolean {
    const group = CUE_GROUP[cue] ?? cue;
    const gap = CUE_GAP_MS[group] ?? DEFAULT_GAP_MS;
    const previous = this.last.get(group);
    if (previous !== undefined && now - previous < gap) return false;
    this.last.set(group, now);
    return true;
  }
}

/** The tools that run a spoken confirmation code ("confirmar" + código). */
const CONFIRM_TOOLS = new Set(['confirm_email_send', 'confirm_app_install', 'confirm_screen_action']);
/** Tools whose ending already has its own sound (the link closing). */
const QUIET_TOOLS = new Set(['end_session']);

/** Which cue (if any) an event from the agent deserves. */
export function cueForHudEvent(event: HudEvent): SoundCue | null {
  if (event.type === 'tool') {
    if (QUIET_TOOLS.has(event.name)) return null;
    if (event.status === 'running') return 'toolStart';
    if (event.status === 'error') return 'error';
    return CONFIRM_TOOLS.has(event.name) ? 'confirm' : 'toolDone';
  }
  if (event.type === 'card' && event.kind === 'timer' && event.data.status === 'done') return 'timerDone';
  return null;
}

// ───────────────────────── engine ─────────────────────────

let settings = loadSoundSettings();
const listeners = new Set<() => void>();
const limiter = new CueLimiter();
let context: AudioContext | null = null;

export function getSoundSettings(): SoundSettings {
  return settings;
}

export function setSoundSettings(next: Partial<SoundSettings>) {
  settings = {
    enabled: next.enabled ?? settings.enabled,
    volume: next.volume === undefined ? settings.volume : clampVolume(next.volume),
  };
  saveSoundSettings(settings);
  listeners.forEach((listener) => listener());
}

export function subscribeSoundSettings(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function audioContext(): AudioContext | null {
  if (typeof AudioContext === 'undefined') return null;
  context ??= new AudioContext();
  // Without a click on the page yet the browser may keep it suspended; the tone is then skipped.
  if (context.state === 'suspended') void context.resume().catch(() => undefined);
  return context;
}

function tone(ctx: AudioContext, start: number, spec: Tone, volume: number) {
  const osc = ctx.createOscillator();
  const env = ctx.createGain();
  const peak = Math.max(0.0002, spec.gain * volume);
  osc.type = spec.wave ?? 'sine';
  osc.frequency.setValueAtTime(spec.from, start);
  if (spec.to !== spec.from) osc.frequency.exponentialRampToValueAtTime(spec.to, start + spec.duration);
  env.gain.setValueAtTime(0.0001, start);
  env.gain.exponentialRampToValueAtTime(peak, start + 0.012);
  env.gain.exponentialRampToValueAtTime(0.0001, start + spec.duration);
  osc.connect(env).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + spec.duration + 0.02);
}

/** Plays a cue unless sounds are off, the volume is zero or the same cue just played (`force`: the test button). */
export function playCue(cue: SoundCue, options: { force?: boolean } = {}) {
  if (!settings.enabled || settings.volume <= 0) return;
  if (!options.force && !limiter.allow(cue, Date.now())) return;
  const ctx = audioContext();
  if (!ctx) return;
  const now = ctx.currentTime + 0.01;
  for (const spec of SOUND_CUES[cue]) tone(ctx, now + spec.at, spec, settings.volume);
}

export function playHudEventSound(event: HudEvent) {
  const cue = cueForHudEvent(event);
  if (cue) playCue(cue);
}
