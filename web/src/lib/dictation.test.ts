import { describe, expect, it } from 'vitest';
import { DICTATION_LINGER_MS, dictationLog, dictationVisible, reduceDictation, splitTail } from './dictation';
import type { DictationEvent } from './types';

const NOW = 1_000_000;
const event = (partial: Partial<DictationEvent>): DictationEvent => ({
  type: 'dictation',
  state: 'typing',
  active: true,
  ts: NOW / 1000,
  ...partial,
});

describe('DIT-29 indicator', () => {
  it('starts empty, then shows the text coming out with the last piece highlighted', () => {
    let state = reduceDictation(null, event({ state: 'on', window: 'Sem título - Bloco de Notas', beep: 'start' }), NOW);
    expect(state.active).toBe(true);
    expect(state.tail).toBe('');
    expect(state.window).toBe('Sem título - Bloco de Notas');

    state = reduceDictation(state, event({ tail: 'Oi, tudo bem?', typed: 'Oi, tudo bem?', heard: 'oi vírgula tudo bem' }), NOW + 10);
    state = reduceDictation(state, event({ tail: 'Oi, tudo bem? Chego em 10 minutos.', typed: ' Chego em 10 minutos.' }), NOW + 20);
    expect(splitTail(state)).toEqual({ before: 'Oi, tudo bem?', typed: ' Chego em 10 minutos.' });
    expect(state.chars).toBe('Oi, tudo bem? Chego em 10 minutos.'.length);
    expect(state.window).toBe('Sem título - Bloco de Notas');
  });

  it('an erase-only command shows the shorter text without a highlight', () => {
    const before = reduceDictation(null, event({ tail: 'Oi, tudo bem', typed: 'Oi, tudo bem' }), NOW);
    const after = reduceDictation(before, event({ tail: 'Oi, tudo', typed: '', erased: 4, commands: ['apaga a última palavra'] }), NOW);
    expect(splitTail(after)).toEqual({ before: 'Oi, tudo', typed: '' });
    expect(after.commands).toEqual(['apaga a última palavra']);
  });

  it('keeps only the end of a long dictation', () => {
    const long = 'palavra '.repeat(60);
    expect(reduceDictation(null, event({ tail: long }), NOW).tail.length).toBe(160);
  });

  it('stays while active and lingers a few seconds after the end', () => {
    const on = reduceDictation(null, event({ state: 'on' }), NOW);
    expect(dictationVisible(on, NOW + 60_000)).toBe(true);
    const off = reduceDictation(on, event({ state: 'off', active: false, message: 'Modo ditado desligado (fim do ditado).' }), NOW);
    expect(dictationVisible(off, NOW + DICTATION_LINGER_MS - 1)).toBe(true);
    expect(dictationVisible(off, NOW + DICTATION_LINGER_MS + 1)).toBe(false);
    expect(dictationVisible(null, NOW)).toBe(false);
  });

  it('a one-shot "escreve aqui" shows its text and counts fresh', () => {
    const prev = reduceDictation(null, event({ tail: 'antigo', typed: 'antigo' }), NOW);
    const once = reduceDictation(prev, event({ state: 'once', active: false, tail: 'Chego em 10 minutos', typed: 'Chego em 10 minutos' }), NOW);
    expect(once.chars).toBe(19);
    expect(splitTail(once).typed).toBe('Chego em 10 minutos');
  });

  it('logs start, end and refusals, not every utterance', () => {
    expect(dictationLog(event({ state: 'on', window: 'WhatsApp' }))?.text).toContain('WhatsApp');
    expect(dictationLog(event({ state: 'warn', message: 'Não escrevi: senha' }))?.level).toBe('warn');
    expect(dictationLog(event({ state: 'typing' }))).toBeNull();
  });
});
