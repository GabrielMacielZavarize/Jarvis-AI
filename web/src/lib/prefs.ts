/**
 * HUD preferences kept in this browser: colour theme, text size, high contrast, scene quality, live caption,
 * ambient mode, reactor hum and where each panel sits. Same pattern as the interface sounds (sounds.ts).
 */
import { useSyncExternalStore } from 'react';
import { DEFAULT_THEME, isTheme, type ThemeId, themeInfo } from './themes';

export type QualityPref = 'auto' | 'high' | 'medium' | 'low';
/** Alto contraste: `auto` segue o sistema (prefers-contrast: more), `on` e `off` são escolha da pessoa. */
export type ContrastPref = 'auto' | 'on' | 'off';
/** Painéis das colunas do Painel (a área inicial); os de Sistema e Ajustes têm lugar fixo. */
export type PanelId = 'briefing' | 'cards' | 'conversation' | 'log';
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
  /** Tamanho do texto de todo o HUD, em % (um dos TEXT_SIZES). */
  textSize: number;
  contrast: ContrastPref;
  layout: PanelLayout;
}

/** Passos do tamanho do texto, em %. 100 é o tamanho de fábrica. */
export const TEXT_SIZES = [90, 100, 110, 120, 130, 140] as const;
export const DEFAULT_TEXT_SIZE = 100;
/** A partir daqui o topo do HUD se compacta (data-text-large no <html>). */
export const LARGE_TEXT_FROM = 120;

export const CONTRAST_LABELS: Record<ContrastPref, string> = {
  auto: 'Automático (segue o sistema)',
  on: 'Ligado',
  off: 'Desligado',
};

export const QUALITY_LABELS: Record<QualityPref, string> = {
  auto: 'Automática',
  high: 'Alta',
  medium: 'Média',
  low: 'Economia',
};

export const PANEL_IDS: PanelId[] = ['briefing', 'cards', 'conversation', 'log'];
export const DEFAULT_LAYOUT: PanelLayout = { left: ['briefing', 'cards'], right: ['conversation', 'log'] };

export const DEFAULT_PREFS: HudPrefs = {
  theme: DEFAULT_THEME,
  quality: 'auto',
  captions: true,
  ambient: true,
  reactorHum: false,
  textSize: DEFAULT_TEXT_SIZE,
  contrast: 'auto',
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

/** O passo mais próximo de um valor qualquer; o que não for número volta ao tamanho de fábrica. */
export function normalizeTextSize(raw: unknown): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return DEFAULT_TEXT_SIZE;
  return TEXT_SIZES.reduce((best, step) => (Math.abs(step - raw) < Math.abs(best - raw) ? step : best));
}

/** O passo seguinte (ou anterior) ao tamanho atual; fica no limite em vez de dar a volta. */
export function stepTextSize(current: number, direction: 1 | -1): number {
  const index = TEXT_SIZES.indexOf(normalizeTextSize(current) as (typeof TEXT_SIZES)[number]);
  return TEXT_SIZES[Math.max(0, Math.min(TEXT_SIZES.length - 1, index + direction))];
}

/** O alto contraste está valendo? A escolha da pessoa manda; sem escolha, vale o que o sistema pede. */
export function contrastIsHigh(pref: ContrastPref, systemWantsMore: boolean): boolean {
  return pref === 'on' || (pref === 'auto' && systemWantsMore);
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
      textSize: normalizeTextSize(data.textSize),
      contrast: typeof data.contrast === 'string' && data.contrast in CONTRAST_LABELS ? (data.contrast as ContrastPref) : DEFAULT_PREFS.contrast,
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

/**
 * O sistema pede mais contraste? `prefers-contrast: more` (macOS "Aumentar contraste", iOS, Android) e
 * `forced-colors: active` (os temas de contraste do Windows) contam igual.
 */
const systemContrast =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-contrast: more), (forced-colors: active)') : null;

/**
 * The theme also styles what lives outside the HUD (boot, expanded panels, pairing screen) and names the tab.
 * O tamanho do texto e o contraste vão no <html> pelo mesmo motivo: a tela de pareamento e o boot também os seguem.
 */
function applyPrefs(current: HudPrefs) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.dataset.theme = current.theme;
  root.dataset.contrast = contrastIsHigh(current.contrast, systemContrast?.matches ?? false) ? 'high' : 'normal';
  root.style.setProperty('--ts', String(current.textSize / 100));
  // A partir de 120% a barra do topo vira ícones (como numa tela estreita) e as marcas encurtam.
  if (current.textSize >= LARGE_TEXT_FROM) root.dataset.textLarge = '';
  else delete root.dataset.textLarge;
  document.title = themeInfo(current.theme).brand;
}

let prefs = loadPrefs();
applyPrefs(prefs);
const listeners = new Set<() => void>();
// Com o contraste em automático, ligar ou desligar a opção do sistema vale na hora, sem recarregar.
systemContrast?.addEventListener?.('change', () => {
  applyPrefs(prefs);
  listeners.forEach((listener) => listener());
});

export function getPrefs(): HudPrefs {
  return prefs;
}

export function setPrefs(next: Partial<HudPrefs>) {
  prefs = { ...prefs, ...next, textSize: next.textSize === undefined ? prefs.textSize : normalizeTextSize(next.textSize), layout: next.layout ? normalizeLayout(next.layout) : prefs.layout };
  applyPrefs(prefs);
  savePrefs(prefs);
  listeners.forEach((listener) => listener());
}

/** O HUD está em alto contraste agora (escolha da pessoa ou, em Automático, o pedido do sistema)? */
export function isHighContrast(): boolean {
  return contrastIsHigh(prefs.contrast, systemContrast?.matches ?? false);
}

export function subscribePrefs(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePrefs(): HudPrefs {
  return useSyncExternalStore(subscribePrefs, getPrefs);
}

export function useHighContrast(): boolean {
  return useSyncExternalStore(subscribePrefs, isHighContrast);
}
