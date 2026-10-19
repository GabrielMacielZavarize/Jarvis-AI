/**
 * Tones for the wake word (WAK-22): a rising chirp when "Jarvis" is heard and a falling one when
 * the link closes for silence. They follow the HUD sound settings (VOZ-30, lib/sounds.ts).
 */
import { playCue } from './sounds';

export function playWakeChime() {
  playCue('wake');
}

export function playSleepChime() {
  playCue('sleep');
}

const DICTATION_CUES = {
  start: 'dictationStart',
  tick: 'dictationTick',
  error: 'dictationError',
  end: 'dictationEnd',
} as const;

/** Dictation mode (DIT-29): Jarvis does not talk while dictating, these beeps do. */
export function playDictationBeep(kind: keyof typeof DICTATION_CUES) {
  playCue(DICTATION_CUES[kind]);
}
