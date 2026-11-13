import { describe, expect, it } from 'vitest';
import {
  contrastIsHigh,
  DEFAULT_LAYOUT,
  DEFAULT_PREFS,
  DEFAULT_TEXT_SIZE,
  movePanel,
  normalizeLayout,
  normalizeTextSize,
  parsePrefs,
  stepTextSize,
  TEXT_SIZES,
} from './prefs';

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
    // "system" era um painel de coluna antes das áreas de trabalho: um layout salvo antigo perde só ele.
    expect(normalizeLayout({ left: ['log', 'log', 'nope'], right: ['system', 'briefing'] })).toEqual({
      left: ['log', 'cards'],
      right: ['briefing', 'conversation'],
    });
    expect(normalizeLayout(undefined)).toEqual(DEFAULT_LAYOUT);
  });

  it('moves a panel to another column or position', () => {
    expect(movePanel(DEFAULT_LAYOUT, 'log', 'left', 0)).toEqual({
      left: ['log', 'briefing', 'cards'],
      right: ['conversation'],
    });
    expect(movePanel(DEFAULT_LAYOUT, 'briefing', 'left', 99).left).toEqual(['cards', 'briefing']);
  });
});

describe('tamanho do texto', () => {
  it('vem em 100% e o que não é um passo vai para o passo mais próximo', () => {
    expect(DEFAULT_PREFS.textSize).toBe(DEFAULT_TEXT_SIZE);
    expect(DEFAULT_TEXT_SIZE).toBe(100);
    expect(TEXT_SIZES[0]).toBe(90);
    expect(TEXT_SIZES[TEXT_SIZES.length - 1]).toBe(140);
    expect(normalizeTextSize(110)).toBe(110);
    expect(normalizeTextSize(113)).toBe(110);
    expect(normalizeTextSize(500)).toBe(140);
    expect(normalizeTextSize(10)).toBe(90);
    expect(normalizeTextSize('grande')).toBe(100);
    expect(normalizeTextSize(Number.NaN)).toBe(100);
    expect(normalizeTextSize(null)).toBe(100);
  });

  it('anda um passo de cada vez e para nos limites', () => {
    expect(stepTextSize(100, 1)).toBe(110);
    expect(stepTextSize(100, -1)).toBe(90);
    expect(stepTextSize(90, -1)).toBe(90);
    expect(stepTextSize(140, 1)).toBe(140);
    expect(stepTextSize(133, 1)).toBe(140);
  });

  it('volta do que foi salvo, e valor inválido cai no padrão', () => {
    expect(parsePrefs(JSON.stringify({ textSize: 130 })).textSize).toBe(130);
    expect(parsePrefs(JSON.stringify({ textSize: 127 })).textSize).toBe(130);
    expect(parsePrefs(JSON.stringify({ textSize: '130%' })).textSize).toBe(100);
  });
});

describe('alto contraste', () => {
  it('vem em automático e só aceita as três escolhas', () => {
    expect(DEFAULT_PREFS.contrast).toBe('auto');
    expect(parsePrefs(JSON.stringify({ contrast: 'on' })).contrast).toBe('on');
    expect(parsePrefs(JSON.stringify({ contrast: 'off' })).contrast).toBe('off');
    expect(parsePrefs(JSON.stringify({ contrast: 'maximo' })).contrast).toBe('auto');
    expect(parsePrefs(JSON.stringify({ contrast: true })).contrast).toBe('auto');
  });

  it('a escolha da pessoa manda; em automático vale o pedido do sistema', () => {
    expect(contrastIsHigh('on', false)).toBe(true);
    expect(contrastIsHigh('off', true)).toBe(false);
    expect(contrastIsHigh('auto', true)).toBe(true);
    expect(contrastIsHigh('auto', false)).toBe(false);
  });

  it('preferências antigas, sem os campos novos, ganham os padrões', () => {
    const old = parsePrefs(JSON.stringify({ theme: 'friday', quality: 'low' }));
    expect(old).toMatchObject({ theme: 'friday', quality: 'low', textSize: 100, contrast: 'auto' });
  });
});
