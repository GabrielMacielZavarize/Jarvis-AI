/**
 * The mode the HUD paints. The agent goes listening → thinking → speaking in fractions of a second
 * and drops to "listening" in the pauses between sentences; repainting the whole HUD for each of
 * those made it blink. A mode only shows after it has held for a moment; link, failure and voice
 * changes still show at once.
 */
import type { JarvisMode } from './types';

/** A short "thinking" right before the voice (the usual turn) does not turn the HUD amber. */
export const THINKING_SETTLE_MS = 450;
/** Pauses between sentences keep the speaking look. */
export const LISTENING_SETTLE_MS = 700;

const LINK_MODES: ReadonlySet<JarvisMode> = new Set(['offline', 'standby', 'connecting', 'error']);

/** How long `next` must hold before the HUD switches from `shown` to it (0: right away). */
export function settleDelay(shown: JarvisMode, next: JarvisMode): number {
  if (shown === next || LINK_MODES.has(next) || LINK_MODES.has(shown)) return 0;
  if (next === 'thinking') return THINKING_SETTLE_MS;
  if (next === 'listening') return LISTENING_SETTLE_MS;
  return 0;
}
