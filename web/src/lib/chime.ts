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
