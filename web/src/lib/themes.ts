/**
 * Colour themes of the HUD. The CSS palette comes from `:root[data-theme]` (global.css) and the
 * 3D scene from SCENE_LOOKS below; both keep the meaning of each mode (processing, failure).
 */
import type { JarvisMode } from './types';

export type ThemeId = 'jarvis' | 'mark3' | 'friday' | 'stealth';

export interface ThemeInfo {
  id: ThemeId;
  label: string;
  hint: string;
  /** Primary and accent, for the swatch in Ajustes. */
  swatch: [string, string];
}

export const THEMES: ThemeInfo[] = [
  { id: 'jarvis', label: 'J.A.R.V.I.S.', hint: 'Ciano e âmbar, o padrão', swatch: ['#5ff4ff', '#ffb648'] },
  { id: 'mark3', label: 'Mark III', hint: 'Dourado e vermelho da armadura', swatch: ['#ffbe50', '#ff5440'] },
  { id: 'friday', label: 'F.R.I.D.A.Y.', hint: 'Violeta e rosa', swatch: ['#be96ff', '#ff82dc'] },
  { id: 'stealth', label: 'Stealth', hint: 'Prata com verde-água, discreto', swatch: ['#e1ebf2', '#5fe0c8'] },
];

export const DEFAULT_THEME: ThemeId = 'jarvis';

export function isTheme(value: unknown): value is ThemeId {
  return THEMES.some((theme) => theme.id === value);
}

export interface SceneLook {
  primary: string;
  secondary: string;
  accent: string;
}

/** Colours of the 3D scene per theme and mode; missing modes use the J.A.R.V.I.S. look. */
export const SCENE_LOOKS: Record<Exclude<ThemeId, 'jarvis'>, Partial<Record<JarvisMode, SceneLook>>> = {
  mark3: {
    offline: { primary: '#8a6a3a', secondary: '#2a1406', accent: '#8a4a3a' },
    standby: { primary: '#ffb43c', secondary: '#7a1208', accent: '#ff4b3a' },
    connecting: { primary: '#ffe2a0', secondary: '#9a2a10', accent: '#ff6a4a' },
    listening: { primary: '#ffc85a', secondary: '#8c1a0c', accent: '#ff5a40' },
    thinking: { primary: '#fff1d6', secondary: '#b84a10', accent: '#ffb43c' },
    speaking: { primary: '#ffd98a', secondary: '#a81e10', accent: '#ff6a4a' },
  },
  friday: {
    offline: { primary: '#6a5a8a', secondary: '#1a0c34', accent: '#8a5a7a' },
    standby: { primary: '#b48cff', secondary: '#3c1a8c', accent: '#ff7ad9' },
    connecting: { primary: '#e0d0ff', secondary: '#4a22a8', accent: '#ff9ae6' },
    listening: { primary: '#c09cff', secondary: '#4220a0', accent: '#ff7ad9' },
    thinking: { primary: '#ff9ae6', secondary: '#8c1a6c', accent: '#b48cff' },
    speaking: { primary: '#d8c2ff', secondary: '#5a2ac0', accent: '#ff8ae0' },
  },
  stealth: {
    offline: { primary: '#6a7a84', secondary: '#1a2228', accent: '#4a7a70' },
    standby: { primary: '#d8e2ea', secondary: '#34424e', accent: '#5fe0c8' },
    connecting: { primary: '#f2f6f8', secondary: '#46586a', accent: '#7ff0da' },
    listening: { primary: '#e6eef4', secondary: '#3c4c5a', accent: '#5fe0c8' },
    thinking: { primary: '#5fe0c8', secondary: '#0c5a4c', accent: '#e6eef4' },
    speaking: { primary: '#ffffff', secondary: '#5a6e7c', accent: '#7ff0da' },
  },
};

/** Theme colours for a mode, or null when the J.A.R.V.I.S. look applies (and always on failure). */
export function sceneLook(theme: ThemeId, mode: JarvisMode): SceneLook | null {
  if (theme === 'jarvis' || mode === 'error') return null;
  return SCENE_LOOKS[theme][mode] ?? null;
}
