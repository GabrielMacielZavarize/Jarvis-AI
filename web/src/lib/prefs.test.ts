import { describe, expect, it } from 'vitest';
import { DEFAULT_LAYOUT, DEFAULT_PREFS, movePanel, normalizeLayout, parsePrefs } from './prefs';

describe('parsePrefs', () => {
  it('falls back to the defaults for missing or broken values', () => {
    expect(parsePrefs(null)).toEqual(DEFAULT_PREFS);
    expect(parsePrefs('{não é json')).toEqual(DEFAULT_PREFS);
    expect(parsePrefs(JSON.stringify({ theme: 'rosa-choque', quality: 'ultra', captions: 'sim' }))).toEqual(DEFAULT_PREFS);
  });

  it('keeps valid choices', () => {
    const prefs = parsePrefs(JSON.stringify({ theme: 'mark3', quality: 'low', captions: false, reactorHum: true }));
    expect(prefs).toMatchObject({ theme: 'mark3', quality: 'low', captions: false, reactorHum: true, ambient: true });
  });
});

describe('panel layout', () => {
  it('shows every panel exactly once, whatever was saved', () => {
    expect(normalizeLayout({ left: ['log', 'log', 'nope'], right: ['system'] })).toEqual({
      left: ['log', 'lan', 'cards'],
      right: ['system', 'conversation', 'gestures', 'health'],
    });
    expect(normalizeLayout(undefined)).toEqual(DEFAULT_LAYOUT);
  });

  it('moves a panel to another column or position', () => {
    expect(movePanel(DEFAULT_LAYOUT, 'log', 'left', 0)).toEqual({
      left: ['log', 'system', 'lan', 'cards'],
      right: ['conversation', 'gestures', 'health'],
    });
    expect(movePanel(DEFAULT_LAYOUT, 'system', 'left', 99).left).toEqual(['lan', 'cards', 'system']);
  });
});
