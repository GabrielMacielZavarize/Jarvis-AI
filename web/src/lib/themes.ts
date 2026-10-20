/**
 * Personas of the HUD (the themes in Ajustes). Each one is a whole identity, not only a palette:
 * who answers (name, how they address the user; the agent switches persona and voice, personas.py),
 * the boot, the 3D core (shell, rings, spectrum, plasma, particles, floor), the panels' shape and
 * fonts (`:root[data-theme]` in global.css and styles/personas.css) and the interface sounds. Every persona keeps the
 * meaning of the modes: processing and failure look different in all of them.
 */
import type { JarvisMode } from './types';

export type ThemeId = 'jarvis' | 'mark3' | 'friday' | 'stealth';

/** The reactor shell around the plasma. */
export type ShellStyle = 'lattice' | 'reactor' | 'gyro' | 'veil';
/** The set of HUD rings around the core. */
export type RingStyle = 'classic' | 'tactical' | 'soft' | 'minimal';

export interface SceneStyle {
  shell: ShellStyle;
  rings: RingStyle;
  spectrum: { bars: number; width: number; length: number; dots: boolean };
  /** Plasma noise: low frequency = liquid, high = turbulent; amp scales the displacement. */
  plasma: { freq: number; detail: number; amp: number; bands: number; rays: number };
  /** Particle disk: multiplier of the quality profile count, tilt and orbit speed (negative = reverse). */
  disk: { count: number; tilt: [number, number, number]; spin: number };
  orbits: number;
  /** Floating dust: colour and multiplier of the quality profile count. */
  sparkle: { color: string; count: number };
  beam: boolean;
  bloom: number;
  /** Multiplier of every rotation and animation. */
  speed: number;
  /** Floor grid cell sizes and whether the radar sweeps. */
  floor: { minor: number; major: number; sweep: boolean; glow: number };
}

export interface SoundStyle {
  /** Transposes every tone (0.8 = lower, 1.25 = brighter). */
  pitch: number;
  /** Oscillator for tones that do not ask for one. */
  wave: OscillatorType;
  /** Volume multiplier. */
  gain: number;
}

export interface ThemeInfo {
  id: ThemeId;
  label: string;
  hint: string;
  /** Primary and accent, for the swatch in Ajustes. */
  swatch: [string, string];
  /** Name on the top bar, the boot and the pairing screen. */
  brand: string;
  tagline: string;
  /** Who speaks in the transcript and the caption. */
  speaker: string;
  /** How the persona addresses the user (the simulation's lines use it too). */
  address: string;
  boot: { steps: string[]; online: string; stepMs: number };
  scene: SceneStyle;
  sound: SoundStyle;
}

const JARVIS_SCENE: SceneStyle = {
  shell: 'lattice',
  rings: 'classic',
  spectrum: { bars: 120, width: 0.022, length: 0.44, dots: false },
  plasma: { freq: 1.6, detail: 4.2, amp: 1, bands: 18, rays: 6 },
  disk: { count: 1, tilt: [1.22, 0.18, 0], spin: 1 },
  orbits: 3,
  sparkle: { color: '#7fe9ff', count: 1 },
  beam: true,
  bloom: 1,
  speed: 1,
  floor: { minor: 1, major: 5, sweep: true, glow: 1 },
};

export const THEMES: ThemeInfo[] = [
  {
    id: 'jarvis',
    label: 'J.A.R.V.I.S.',
    hint: 'O mordomo britânico: ciano e âmbar, núcleo em treliça, voz grave e calma',
    swatch: ['#5ff4ff', '#ffb648'],
    brand: 'J.A.R.V.I.S.',
    tagline: 'Just A Rather Very Intelligent System',
    speaker: 'J.A.R.V.I.S.',
    address: 'senhor',
    boot: {
      steps: [
        'Inicializando núcleo neural',
        'Calibrando matriz holográfica',
        'Carregando protocolos de voz',
        'Sincronizando sensores ambientais',
        'Verificando integridade dos sistemas',
      ],
      online: 'Todos os sistemas online',
      stepMs: 380,
    },
    scene: JARVIS_SCENE,
    sound: { pitch: 1, wave: 'sine', gain: 1 },
  },
  {
    id: 'mark3',
    label: 'Mark III',
    hint: 'Dentro da armadura: reator arc, mira tática, placas angulosas e respostas de relatório',
    swatch: ['#ffbe50', '#ff5440'],
    brand: 'MARK III',
    tagline: 'J.A.R.V.I.S. · Interface tática da armadura',
    speaker: 'J.A.R.V.I.S.',
    address: 'senhor',
    boot: {
      steps: [
        'Pressurizando o reator arc',
        'Alinhando os repulsores',
        'Calibrando a mira tática',
        'Sincronizando os sensores da armadura',
        'Verificando a integridade do casco',
      ],
      online: 'Armadura Mark III online',
      stepMs: 320,
    },
    scene: {
      shell: 'reactor',
      rings: 'tactical',
      spectrum: { bars: 72, width: 0.05, length: 0.38, dots: false },
      plasma: { freq: 2.4, detail: 6.5, amp: 0.8, bands: 26, rays: 10 },
      disk: { count: 0.6, tilt: [1.42, 0.05, 0], spin: 1.8 },
      orbits: 1,
      sparkle: { color: '#ffb46a', count: 0.7 },
      beam: true,
      bloom: 1.1,
      speed: 1.15,
      floor: { minor: 0.5, major: 2.5, sweep: true, glow: 1.1 },
    },
    sound: { pitch: 0.78, wave: 'triangle', gain: 1.05 },
  },
  {
    id: 'friday',
    label: 'F.R.I.D.A.Y.',
    hint: 'A sucessora: voz feminina, direta e calorosa; núcleo líquido, giroscópio e vidro arredondado',
    swatch: ['#be96ff', '#ff82dc'],
    brand: 'F.R.I.D.A.Y.',
    tagline: 'Female Replacement Intelligent Digital Assistant Youth',
    speaker: 'F.R.I.D.A.Y.',
    address: 'chefe',
    boot: {
      steps: [
        'Acordando a F.R.I.D.A.Y.',
        'Carregando a matriz de personalidade',
        'Afinando a voz',
        'Sincronizando com a rede da casa',
        'Conferindo os sistemas',
      ],
      online: 'F.R.I.D.A.Y. na escuta',
      stepMs: 360,
    },
    scene: {
      shell: 'gyro',
      rings: 'soft',
      spectrum: { bars: 120, width: 0.03, length: 0.4, dots: true },
      plasma: { freq: 1.05, detail: 2.6, amp: 1.35, bands: 10, rays: 4 },
      disk: { count: 1.2, tilt: [0.95, -0.32, 0.2], spin: -0.7 },
      orbits: 3,
      sparkle: { color: '#dcc0ff', count: 1.3 },
      beam: true,
      bloom: 1.15,
      speed: 0.85,
      floor: { minor: 1.6, major: 8, sweep: false, glow: 0.8 },
    },
    sound: { pitch: 1.26, wave: 'sine', gain: 0.9 },
  },
  {
    id: 'stealth',
    label: 'Stealth',
    hint: 'Discreto: prata, sem brilho nem partículas, sons baixos, voz sussurrada e respostas mínimas',
    swatch: ['#e1ebf2', '#5fe0c8'],
    brand: 'STEALTH',
    tagline: 'J.A.R.V.I.S. · Modo discreto',
    speaker: 'J.A.R.V.I.S.',
    address: 'senhor',
    boot: {
      steps: ['Reduzindo a assinatura', 'Silenciando os sistemas', 'Modo discreto'],
      online: 'Discreto e online',
      stepMs: 260,
    },
    scene: {
      shell: 'veil',
      rings: 'minimal',
      spectrum: { bars: 90, width: 0.01, length: 0.26, dots: false },
      plasma: { freq: 1.3, detail: 3, amp: 0.5, bands: 14, rays: 0 },
      disk: { count: 0.25, tilt: [1.22, 0.18, 0], spin: 0.5 },
      orbits: 0,
      sparkle: { color: '#cfd8de', count: 0 },
      beam: false,
      bloom: 0.7,
      speed: 0.7,
      floor: { minor: 2, major: 10, sweep: false, glow: 0.5 },
    },
    sound: { pitch: 0.92, wave: 'sine', gain: 0.45 },
  },
];

export const DEFAULT_THEME: ThemeId = 'jarvis';

export function isTheme(value: unknown): value is ThemeId {
  return THEMES.some((theme) => theme.id === value);
}

export function themeInfo(id: ThemeId): ThemeInfo {
  return THEMES.find((theme) => theme.id === id) ?? THEMES[0];
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

/** The simulation's lines in the persona's voice ("senhor" → "chefe" for F.R.I.D.A.Y.). */
export function inPersona(text: string, theme: ThemeId): string {
  const { address } = themeInfo(theme);
  if (address === 'senhor') return text;
  return text.replace(/\bsenhor\b/g, address).replace(/\bSenhor\b/g, address[0].toUpperCase() + address.slice(1));
}
