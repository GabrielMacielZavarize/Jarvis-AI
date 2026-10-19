import { describe, expect, it } from 'vitest';
import { coreActivity, FLASH_MS, flashLevel, lastToolResult, markToolResult } from './coreActivity';

describe('coreActivity', () => {
  it('shows "executando" while a tool runs, even if the model is thinking', () => {
    expect(coreActivity('thinking', 'get_weather')).toBe('executing');
    expect(coreActivity('listening', 'set_timer')).toBe('executing');
  });

  it('shows "pensando" while the model works without a tool', () => {
    expect(coreActivity('thinking', null)).toBe('thinking');
    expect(coreActivity('speaking', null)).toBe('idle');
    expect(coreActivity('listening', null)).toBe('idle');
  });

  it('stays still without a link', () => {
    expect(coreActivity('standby', 'get_weather')).toBe('idle');
    expect(coreActivity('offline', null)).toBe('idle');
    expect(coreActivity('error', 'search_web')).toBe('idle');
  });
});

describe('tool flash', () => {
  it('fades out after the tool ends', () => {
    markToolResult('done', 1000);
    const result = lastToolResult();
    expect(result).toEqual({ ok: true, at: 1000 });
    expect(flashLevel(result, 1000)).toBe(1);
    expect(flashLevel(result, 1000 + FLASH_MS / 2)).toBeCloseTo(0.5);
    expect(flashLevel(result, 1000 + FLASH_MS)).toBe(0);
    expect(flashLevel(result, 900)).toBe(0);
    expect(flashLevel(null, 1000)).toBe(0);
  });

  it('remembers failures so the flash turns red', () => {
    markToolResult('error', 2000);
    expect(lastToolResult()?.ok).toBe(false);
  });
});
