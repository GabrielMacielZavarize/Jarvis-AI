/**
 * HUD preferences kept in this browser: colour theme, scene quality, live caption, ambient mode,
 * reactor hum and where each panel sits. Same pattern as the interface sounds (sounds.ts).
 */
import { useSyncExternalStore } from 'react';
import { DEFAULT_THEME, isTheme, type ThemeId } from './themes';

export type QualityPref = 'auto' | 'high' | 'medium' | 'low';
export type PanelId = 'system' | 'lan' | 'cards' | 'conversation' | 'log';
export type Column = 'left' | 'right';
export type PanelLayout = Record<Column, PanelId[]>;

export interface HudPrefs {
  theme: ThemeId;
  quality: QualityPref;
  /** Jarvis's words under the core while he speaks. */
  captions: boolean;
  /** Big clock and weather after a few idle minutes without a link. */
  ambient: boolean;
  /** Low hum of the reactor that follows Jarvis's voice. */
  reactorHum: boolean;
  layout: PanelLayout;
}

export const QUALITY_LABELS: Record<QualityPref, string> = {
  auto: 'Automática',
  high: 'Alta',
  medium: 'Média',
  low: 'Economia',
};

export const PANEL_IDS: PanelId[] = ['system', 'lan', 'cards', 'conversation', 'log'];
export const DEFAULT_LAYOUT: PanelLayout = { left: ['system', 'lan', 'cards'], right: ['conversation', 'log'] };

export const DEFAULT_PREFS: HudPrefs = {
  theme: DEFAULT_THEME,
  quality: 'auto',
  captions: true,
  ambient: true,
  reactorHum: false,
  layout: DEFAULT_LAYOUT,
};

export const PREFS_STORAGE_KEY = 'jarvis.hud.prefs';

type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>;

/** Every panel exactly once; unknown ids dropped, missing ones back in their default column. */
export function normalizeLayout(raw: unknown): PanelLayout {
  const source = raw && typeof raw === 'object' ? (raw as Partial<Record<Column, unknown>>) : {};
  const seen = new Set<PanelId>();
  const column = (name: Column) =>
    (Array.isArray(source[name]) ? source[name] : []).filter((id): id is PanelId => {
      if (!PANEL_IDS.includes(id as PanelId) || seen.has(id as PanelId)) return false;
      seen.add(id as PanelId);
      return true;
    });
  const layout: PanelLayout = { left: column('left'), right: column('right') };
  for (const name of ['left', 'right'] as Column[]) {
    for (const id of DEFAULT_LAYOUT[name]) if (!seen.has(id)) layout[name].push(id);
  }
  return layout;
}

/** The layout with `id` taken out of its column and put at `index` of `column`. */
export function movePanel(layout: PanelLayout, id: PanelId, column: Column, index: number): PanelLayout {
  const next: PanelLayout = {
    left: layout.left.filter((item) => item !== id),
    right: layout.right.filter((item) => item !== id),
  };
  next[column].splice(Math.max(0, Math.min(index, next[column].length)), 0, id);
  return next;
}

export function parsePrefs(raw: string | null): HudPrefs {
  if (!raw) return { ...DEFAULT_PREFS };
  try {
    const data = JSON.parse(raw) as Partial<Record<keyof HudPrefs, unknown>>;
    const flag = (value: unknown, fallback: boolean) => (typeof value === 'boolean' ? value : fallback);
    return {
      theme: isTheme(data.theme) ? data.theme : DEFAULT_PREFS.theme,
      quality:
        typeof data.quality === 'string' && data.quality in QUALITY_LABELS ? (data.quality as QualityPref) : DEFAULT_PREFS.quality,
      captions: flag(data.captions, DEFAULT_PREFS.captions),
      ambient: flag(data.ambient, DEFAULT_PREFS.ambient),
      reactorHum: flag(data.reactorHum, DEFAULT_PREFS.reactorHum),
      layout: normalizeLayout(data.layout),
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

function browserStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadPrefs(storage: Storage | null = browserStorage()): HudPrefs {
  try {
    return parsePrefs(storage?.getItem(PREFS_STORAGE_KEY) ?? null);
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

function savePrefs(prefs: HudPrefs, storage: Storage | null = browserStorage()) {
  try {
    storage?.setItem(PREFS_STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // Private windows may refuse storage; the choice still lasts until the tab closes.
  }
}

/** The theme also styles what lives outside the HUD (boot, expanded panels, pairing screen). */
function applyTheme(theme: ThemeId) {
  if (typeof document !== 'undefined') document.documentElement.dataset.theme = theme;
}

let prefs = loadPrefs();
applyTheme(prefs.theme);
const listeners = new Set<() => void>();

export function getPrefs(): HudPrefs {
  return prefs;
}

export function setPrefs(next: Partial<HudPrefs>) {
  prefs = { ...prefs, ...next, layout: next.layout ? normalizeLayout(next.layout) : prefs.layout };
  applyTheme(prefs.theme);
  savePrefs(prefs);
  listeners.forEach((listener) => listener());
}

export function subscribePrefs(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePrefs(): HudPrefs {
  return useSyncExternalStore(subscribePrefs, getPrefs);
}
