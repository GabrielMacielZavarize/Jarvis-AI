/**
 * Short synthesized tones for the wake word (WAK-22): a rising chirp when "Jarvis" is heard and a
 * falling one when the link closes for silence. No audio files; Web Audio only.
 */
let context: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (typeof AudioContext === 'undefined') return null;
  context ??= new AudioContext();
  // Without a click on the page yet the browser may keep it suspended; the tone is then skipped.
  if (context.state === 'suspended') void context.resume().catch(() => undefined);
  return context;
}

function tone(ctx: AudioContext, start: number, from: number, to: number, duration: number, gain: number) {
  const osc = ctx.createOscillator();
  const env = ctx.createGain();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(from, start);
  osc.frequency.exponentialRampToValueAtTime(to, start + duration);
  env.gain.setValueAtTime(0.0001, start);
  env.gain.exponentialRampToValueAtTime(gain, start + 0.012);
  env.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(env).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + duration + 0.02);
}

export function playWakeChime() {
  const ctx = audioContext();
  if (!ctx) return;
  const now = ctx.currentTime + 0.01;
  tone(ctx, now, 660, 990, 0.09, 0.16);
  tone(ctx, now + 0.1, 990, 1480, 0.14, 0.14);
}

export function playSleepChime() {
  const ctx = audioContext();
  if (!ctx) return;
  const now = ctx.currentTime + 0.01;
  tone(ctx, now, 990, 660, 0.12, 0.1);
  tone(ctx, now + 0.13, 660, 440, 0.18, 0.08);
}

/** Dictation mode (DIT-29): Jarvis does not talk while dictating, these beeps do. */
export function playDictationBeep(kind: 'start' | 'tick' | 'error' | 'end') {
  const ctx = audioContext();
  if (!ctx) return;
  const now = ctx.currentTime + 0.01;
  if (kind === 'start') {
    tone(ctx, now, 880, 880, 0.07, 0.12);
    tone(ctx, now + 0.09, 1320, 1320, 0.09, 0.12);
  } else if (kind === 'tick') {
    tone(ctx, now, 1500, 1400, 0.045, 0.07);
  } else if (kind === 'error') {
    tone(ctx, now, 330, 280, 0.18, 0.12);
  } else {
    tone(ctx, now, 1320, 1320, 0.07, 0.1);
    tone(ctx, now + 0.09, 880, 660, 0.12, 0.1);
  }
}
