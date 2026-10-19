import { Color } from 'three';
import { levels, sampleAudio } from '../lib/audio';
import { coreActivity, flashLevel, lastToolResult } from '../lib/coreActivity';
import { useHud } from '../lib/hudStore';
import type { JarvisMode } from '../lib/types';

interface ModeLook {
  primary: string;
  secondary: string;
  accent: string;
  /** Rotation / animation speed multiplier. */
  speed: number;
  /** Overall brightness multiplier. */
  glow: number;
}

export const MODE_LOOK: Record<JarvisMode, ModeLook> = {
  offline: { primary: '#2f6f8f', secondary: '#0b2a3d', accent: '#5a7f94', speed: 0.25, glow: 0.45 },
  standby: { primary: '#4fdcff', secondary: '#0d4f8c', accent: '#ffb648', speed: 0.45, glow: 0.75 },
  connecting: { primary: '#86ecff', secondary: '#1a66c9', accent: '#ffd27a', speed: 1.8, glow: 0.95 },
  listening: { primary: '#3ef0ff', secondary: '#0e62b8', accent: '#ffb648', speed: 0.8, glow: 1.0 },
  thinking: { primary: '#ffc15e', secondary: '#a8530c', accent: '#5ff4ff', speed: 2.4, glow: 1.05 },
  speaking: { primary: '#8ffaff', secondary: '#1584e0', accent: '#ffcf70', speed: 1.1, glow: 1.25 },
  error: { primary: '#ff4b4b', secondary: '#6d0d16', accent: '#ffa04b', speed: 0.6, glow: 0.9 },
};

/**
 * Smoothed, per-frame values shared by every scene component.
 * Updated by <SceneDriver /> (negative useFrame priority so it runs first).
 */
export const scene = {
  primary: new Color(MODE_LOOK.standby.primary),
  secondary: new Color(MODE_LOOK.standby.secondary),
  accent: new Color(MODE_LOOK.standby.accent),
  speed: MODE_LOOK.standby.speed,
  glow: MODE_LOOK.standby.glow,
  /** Accumulated, speed-scaled time — use instead of clock time for rotations. */
  phase: 0,
  energy: 0,
  agent: 0,
  user: 0,
  /** 0 → 1 pulse fired whenever the mode changes. */
  surge: 0,
  /** 0 → 1 while the globe shows network connections (driven by EarthGlobe). */
  network: 0,
  /** 0 → 1 while the model is working on a reply (VOZ-30). */
  thinking: 0,
  /** 0 → 1 while a tool runs. */
  executing: 0,
  /** 1 → 0 right after a tool finishes; `flashOk` false paints it red. */
  flash: 0,
  flashOk: true,
  mode: 'standby' as JarvisMode,
};

const target = {
  primary: new Color(),
  secondary: new Color(),
  accent: new Color(),
};

export function updateScene(time: number, delta: number) {
  sampleAudio(time);

  const { mode, activeTool } = useHud.getState();
  const effective: JarvisMode = activeTool && mode !== 'speaking' ? 'thinking' : mode;
  if (effective !== scene.mode) {
    scene.mode = effective;
    scene.surge = 1;
  }

  const look = MODE_LOOK[effective];
  const k = 1 - Math.exp(-delta * 3.2);
  target.primary.set(look.primary);
  target.secondary.set(look.secondary);
  target.accent.set(look.accent);
  scene.primary.lerp(target.primary, k);
  scene.secondary.lerp(target.secondary, k);
  scene.accent.lerp(target.accent, k);
  scene.speed += (look.speed - scene.speed) * k;
  scene.glow += (look.glow - scene.glow) * k;

  scene.agent = levels.agent;
  scene.user = levels.user;
  const energyTarget = Math.max(levels.agent, levels.user * 0.85);
  scene.energy += (energyTarget - scene.energy) * (1 - Math.exp(-delta * 10));
  scene.phase += delta * scene.speed;
  scene.surge = Math.max(0, scene.surge - delta * 1.4);

  const activity = coreActivity(mode, activeTool);
  const ka = 1 - Math.exp(-delta * 5);
  scene.thinking += ((activity === 'thinking' ? 1 : 0) - scene.thinking) * ka;
  scene.executing += ((activity === 'executing' ? 1 : 0) - scene.executing) * ka;
  const result = lastToolResult();
  scene.flash = flashLevel(result, Date.now());
  scene.flashOk = result?.ok ?? true;
}
