/**
 * Quality of the 3D scene. "Automática" starts at what the device handles (a phone gets the lighter
 * scene, LAN-26) and steps down when the frame rate stays low, so a weak PC keeps the HUD smooth.
 */
import type { QualityPref } from './prefs';
import type { SceneLevel } from './types';

export interface QualityProfile {
  dpr: [number, number];
  sparkles: number;
  particles: number;
  /** full: bloom + aberration + noise + vignette; bloom: bloom only; lite: half-resolution bloom. */
  postprocessing: 'full' | 'bloom' | 'lite';
  beam: boolean;
}

export const QUALITY_PROFILES: Record<SceneLevel, QualityProfile> = {
  high: { dpr: [1, 1.75], sparkles: 90, particles: 2600, postprocessing: 'full', beam: true },
  medium: { dpr: [1, 1.25], sparkles: 40, particles: 1600, postprocessing: 'bloom', beam: true },
  low: { dpr: [0.75, 1], sparkles: 0, particles: 900, postprocessing: 'lite', beam: false },
};

export const LEVEL_LABELS: Record<SceneLevel, string> = { high: 'Alta', medium: 'Média', low: 'Economia' };

const ORDER: SceneLevel[] = ['low', 'medium', 'high'];

/** Below this the scene steps down; this many good windows in a row let it step back up. */
export const LOW_FPS = 40;
export const GOOD_FPS = 57;
export const GOOD_WINDOWS = 5;

export function deviceCeiling(lite: boolean): SceneLevel {
  return lite ? 'medium' : 'high';
}

export function fixedLevel(pref: QualityPref, lite: boolean): SceneLevel {
  return pref === 'auto' ? deviceCeiling(lite) : pref;
}

export interface AutoState {
  level: SceneLevel;
  /** Best level the device may use. */
  ceiling: SceneLevel;
  /** Good windows in a row at this level. */
  good: number;
  /** Times each level ran slow; after two it is not tried again in this tab. */
  strikes: Partial<Record<SceneLevel, number>>;
}

export function startAuto(lite: boolean): AutoState {
  const level = deviceCeiling(lite);
  return { level, ceiling: level, good: 0, strikes: {} };
}

/** One measuring window (a few seconds) of the automatic mode. */
export function autoStep(state: AutoState, fps: number): AutoState {
  const index = ORDER.indexOf(state.level);
  if (fps < LOW_FPS && index > 0) {
    const strikes = { ...state.strikes, [state.level]: (state.strikes[state.level] ?? 0) + 1 };
    return { ...state, level: ORDER[index - 1], good: 0, strikes };
  }
  if (fps < GOOD_FPS || state.level === state.ceiling) return { ...state, good: 0 };
  const up = ORDER[index + 1];
  if ((state.strikes[up] ?? 0) >= 2) return { ...state, good: 0 };
  const good = state.good + 1;
  return good >= GOOD_WINDOWS ? { ...state, level: up, good: 0 } : { ...state, good };
}
