import { describe, expect, it } from 'vitest';
import { PROTOCOLS, TOOL_LABELS, toolCode } from './catalog';

describe('toolCode', () => {
  it('gives the protocol code of a tool', () => {
    expect(toolCode('get_weather')).toBe('WX-01');
    expect(toolCode('manage_screens')).toBe('JAN-13');
    expect(toolCode('confirm_calendar_change')).toBe('AGD-27');
  });

  it('falls back to a generic code for unknown tools', () => {
    expect(toolCode('teleport')).toBe('PRT');
  });

  it('agrees with the Protocolos panel', () => {
    for (const protocol of PROTOCOLS) expect(toolCode(protocol.id)).toBe(protocol.code);
  });

  it('knows every tool the HUD has a label for', () => {
    expect(Object.keys(TOOL_LABELS).filter((name) => toolCode(name) === 'PRT')).toEqual([]);
  });
});
