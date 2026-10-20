import { describe, expect, it } from 'vitest';
import { LISTENING_SETTLE_MS, settleDelay, THINKING_SETTLE_MS } from './visualMode';

describe('settleDelay', () => {
  it('waits before painting a short thinking', () => {
    expect(settleDelay('listening', 'thinking')).toBe(THINKING_SETTLE_MS);
    expect(settleDelay('speaking', 'thinking')).toBe(THINKING_SETTLE_MS);
  });

  it('keeps the speaking look through the pauses between sentences', () => {
    expect(settleDelay('speaking', 'listening')).toBe(LISTENING_SETTLE_MS);
    expect(settleDelay('thinking', 'listening')).toBe(LISTENING_SETTLE_MS);
  });

  it('shows the voice, the link and failures at once', () => {
    expect(settleDelay('thinking', 'speaking')).toBe(0);
    expect(settleDelay('listening', 'speaking')).toBe(0);
    expect(settleDelay('speaking', 'error')).toBe(0);
    expect(settleDelay('listening', 'standby')).toBe(0);
    expect(settleDelay('standby', 'connecting')).toBe(0);
    // Right after the link opens, the first "listening" is not held back.
    expect(settleDelay('connecting', 'listening')).toBe(0);
  });

  it('is zero when nothing changes', () => {
    expect(settleDelay('thinking', 'thinking')).toBe(0);
  });
});
