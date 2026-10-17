import { createAudioAnalyser, type LocalAudioTrack, type RemoteAudioTrack } from 'livekit-client';

/**
 * Shared, allocation-free audio levels read by the 3D scene every frame.
 * React never re-renders because of audio: the scene samples this module in useFrame.
 */
export const BANDS = 48;

type Channel = 'agent' | 'user';
type AudioTrack = LocalAudioTrack | RemoteAudioTrack;

interface Source {
  track: AudioTrack;
  mediaStreamTrack: MediaStreamTrack;
  analyser: AnalyserNode;
  bins: Uint8Array<ArrayBuffer>;
  cleanup: () => Promise<void>;
}

export interface SyntheticLevels {
  agent: number;
  user: number;
}

export const levels = {
  agent: 0,
  user: 0,
  agentBands: new Float32Array(BANDS),
  userBands: new Float32Array(BANDS),
};

const sources: Partial<Record<Channel, Source>> = {};
let synthetic: ((time: number) => SyntheticLevels) | null = null;

export function attachTrack(channel: Channel, track: AudioTrack | undefined) {
  const current = sources[channel];
  if (current && current.track === track && current.mediaStreamTrack === track?.mediaStreamTrack) return;
  if (current) {
    void current.cleanup();
    delete sources[channel];
  }
  if (!track?.mediaStreamTrack) return;

  try {
    const { analyser, cleanup } = createAudioAnalyser(track, {
      fftSize: 256,
      smoothingTimeConstant: 0.72,
      minDecibels: -92,
      maxDecibels: -22,
    });
    const context = analyser.context;
    if (context instanceof AudioContext && context.state === 'suspended') void context.resume();
    sources[channel] = {
      track,
      mediaStreamTrack: track.mediaStreamTrack,
      analyser,
      bins: new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount)),
      cleanup,
    };
  } catch (error) {
    console.warn('[jarvis] analisador de áudio indisponível', error);
  }
}

export function setSynthetic(fn: ((time: number) => SyntheticLevels) | null) {
  synthetic = fn;
}

function readBands(source: Source, out: Float32Array): number {
  source.analyser.getByteFrequencyData(source.bins);
  const usable = Math.min(source.bins.length, 72);
  let total = 0;
  for (let i = 0; i < BANDS; i++) {
    // Slightly logarithmic spread so low/mid voice frequencies get more bars.
    const start = Math.floor(Math.pow(i / BANDS, 1.35) * usable) + 1;
    const end = Math.max(start + 1, Math.floor(Math.pow((i + 1) / BANDS, 1.35) * usable) + 1);
    let peak = 0;
    for (let b = start; b < end && b < source.bins.length; b++) peak = Math.max(peak, source.bins[b]);
    const value = Math.pow(peak / 255, 1.6);
    out[i] = out[i] * 0.45 + value * 0.55;
    total += out[i];
  }
  return Math.min(1, (total / BANDS) * 2.1);
}

function syntheticBands(level: number, time: number, out: Float32Array, seed: number) {
  for (let i = 0; i < BANDS; i++) {
    const x = i / BANDS;
    const formant = Math.exp(-Math.pow((x - 0.18) * 4.2, 2)) + 0.6 * Math.exp(-Math.pow((x - 0.45) * 5, 2));
    const flutter = 0.55 + 0.45 * Math.sin(time * (7 + seed) + i * 1.7) * Math.sin(time * 3.3 + i * 0.6);
    const target = level * formant * flutter * 1.25;
    out[i] = out[i] * 0.6 + target * 0.4;
  }
}

function decay(out: Float32Array) {
  for (let i = 0; i < BANDS; i++) out[i] *= 0.86;
}

/** Called once per frame by the scene driver. */
export function sampleAudio(time: number) {
  if (synthetic) {
    const value = synthetic(time);
    levels.agent += (value.agent - levels.agent) * 0.25;
    levels.user += (value.user - levels.user) * 0.25;
    syntheticBands(levels.agent, time, levels.agentBands, 0);
    syntheticBands(levels.user, time, levels.userBands, 2);
    return;
  }

  // Switching microphones restarts the track with a new MediaStreamTrack.
  for (const channel of ['agent', 'user'] as const) {
    const source = sources[channel];
    if (source && source.track.mediaStreamTrack !== source.mediaStreamTrack) attachTrack(channel, source.track);
  }

  const agent = sources.agent;
  const user = sources.user;
  const agentLevel = agent ? readBands(agent, levels.agentBands) : (decay(levels.agentBands), 0);
  const userLevel = user ? readBands(user, levels.userBands) : (decay(levels.userBands), 0);
  levels.agent += (agentLevel - levels.agent) * 0.3;
  levels.user += (userLevel - levels.user) * 0.3;
}
