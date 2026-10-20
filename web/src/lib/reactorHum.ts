/**
 * Reactor hum: a low drone made in the browser (Web Audio, no files) that swells and brightens
 * while Jarvis speaks. Off by default; Ajustes turns it on, and it follows the interface volume.
 */
import { levels } from './audio';
import { getPrefs } from './prefs';
import { audioContext } from './sounds';
import { themeInfo } from './themes';

/** Quiet enough to sit under the voice: the hum is felt more than heard. */
const BASE_GAIN = 0.022;
const SPEAKING_GAIN = 0.05;
const CLOSED_CUTOFF_HZ = 320;
const OPEN_CUTOFF_HZ = 1100;
const UPDATE_MS = 80;

/** Gain and low-pass cutoff for Jarvis's voice energy (0–1) at the interface volume (0–1). */
export function humLevels(energy: number, volume: number): { gain: number; cutoff: number } {
  const voice = Math.min(1, Math.max(0, energy * 1.6));
  return {
    gain: (BASE_GAIN + voice * SPEAKING_GAIN) * Math.min(1, Math.max(0, volume)),
    cutoff: CLOSED_CUTOFF_HZ + voice * (OPEN_CUTOFF_HZ - CLOSED_CUTOFF_HZ),
  };
}

interface Hum {
  stop: () => void;
  setVolume: (volume: number) => void;
}

/** Starts the drone; returns how to change its volume and stop it (it fades out). */
export function startHum(volume: number): Hum | null {
  const ctx = audioContext();
  if (!ctx) return null;
  const master = ctx.createGain();
  master.gain.value = 0;
  const filter = ctx.createBiquadFilter();
  filter.type = 'lowpass';
  filter.frequency.value = CLOSED_CUTOFF_HZ;
  filter.Q.value = 0.8;
  filter.connect(master).connect(ctx.destination);

  // Fundamental, octave and a slightly detuned fifth that beats slowly against it, in the
  // persona's register (the Mark III reactor rumbles lower, F.R.I.D.A.Y. hums higher).
  const { pitch } = themeInfo(getPrefs().theme).sound;
  const voices = [
    { freq: 55, type: 'sine' as OscillatorType, gain: 1 },
    { freq: 110, type: 'triangle' as OscillatorType, gain: 0.35 },
    { freq: 165.6, type: 'sine' as OscillatorType, gain: 0.14 },
  ].map(({ freq, type, gain }) => {
    const osc = ctx.createOscillator();
    const level = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq * pitch;
    level.gain.value = gain;
    osc.connect(level).connect(filter);
    osc.start();
    return osc;
  });

  let current = volume;
  const timer = window.setInterval(() => {
    const { gain, cutoff } = humLevels(levels.agent, current);
    master.gain.setTargetAtTime(gain, ctx.currentTime, 0.12);
    filter.frequency.setTargetAtTime(cutoff, ctx.currentTime, 0.15);
  }, UPDATE_MS);

  return {
    setVolume: (next) => {
      current = next;
    },
    stop: () => {
      window.clearInterval(timer);
      master.gain.setTargetAtTime(0, ctx.currentTime, 0.2);
      for (const osc of voices) osc.stop(ctx.currentTime + 1);
      window.setTimeout(() => master.disconnect(), 1100);
    },
  };
}
