import { describe, expect, it } from 'vitest';
import {
  advance,
  cleanConfig,
  DEFAULT_FOCUS,
  focusReport,
  formatCountdown,
  IDLE_FOCUS,
  parseFocus,
  phaseProgress,
  remainingSeconds,
  skipPhase,
  startFocus,
} from './focus';

const MIN = 60_000;
const T0 = 1_800_000_000_000;

describe('sessão de foco', () => {
  it('começa no primeiro bloco de trabalho', () => {
    const focus = startFocus({ work: 25, rest: 5, cycles: 4 }, T0);
    expect(focus).toMatchObject({ running: true, phase: 'work', cycle: 1, cycles: 4, endsAt: T0 + 25 * MIN });
    expect(remainingSeconds(focus, T0)).toBe(1500);
    expect(remainingSeconds(focus, T0 + 24 * MIN + 30_500)).toBe(30);
    expect(phaseProgress(focus, T0 + 12.5 * MIN)).toBeCloseTo(0.5);
  });

  it('alterna foco e pausa e termina sem pausa depois do último bloco', () => {
    let focus = startFocus({ work: 2, rest: 1, cycles: 2 }, T0);
    expect(advance(focus, T0 + 2 * MIN - 1).events).toEqual([]);

    let step = advance(focus, T0 + 2 * MIN);
    expect(step.events).toEqual(['rest']);
    expect(step.state).toMatchObject({ phase: 'rest', cycle: 1, endsAt: T0 + 3 * MIN });
    focus = step.state;

    step = advance(focus, T0 + 3 * MIN);
    expect(step.events).toEqual(['work']);
    expect(step.state).toMatchObject({ phase: 'work', cycle: 2, endsAt: T0 + 5 * MIN });
    focus = step.state;

    step = advance(focus, T0 + 5 * MIN);
    expect(step.events).toEqual(['done']);
    expect(step.state.running).toBe(false);
    expect(remainingSeconds(step.state, T0 + 5 * MIN)).toBe(0);
  });

  it('uma aba que dormiu passa por todos os blocos sem acumular atraso', () => {
    const focus = startFocus({ work: 10, rest: 5, cycles: 3 }, T0);
    // Acorda aos 27 min: foco (10), pausa (5), foco (10) já passaram; está na segunda pausa.
    const step = advance(focus, T0 + 27 * MIN);
    expect(step.events).toEqual(['rest', 'work', 'rest']);
    expect(step.state).toMatchObject({ phase: 'rest', cycle: 2, endsAt: T0 + 30 * MIN });
    // Horas depois, a sessão simplesmente acabou.
    const late = advance(focus, T0 + 600 * MIN);
    expect(late.events[late.events.length - 1]).toBe('done');
    expect(late.state.running).toBe(false);
  });

  it('pular conta o próximo bloco a partir de agora', () => {
    const focus = startFocus({ work: 25, rest: 5, cycles: 2 }, T0);
    const skipped = skipPhase(focus, T0 + 3 * MIN);
    expect(skipped.events).toEqual(['rest']);
    expect(skipped.state.endsAt).toBe(T0 + 8 * MIN);
    expect(skipPhase(IDLE_FOCUS, T0)).toEqual({ state: IDLE_FOCUS, events: [] });
    const last = skipPhase({ ...focus, cycle: 2 }, T0);
    expect(last.events).toEqual(['done']);
  });

  it('segura os valores dentro dos limites', () => {
    expect(cleanConfig({ work: 0, rest: 999, cycles: -3 })).toEqual({ work: 1, rest: 60, cycles: 1 });
    expect(cleanConfig({ work: 50.4 })).toEqual({ work: 50, rest: DEFAULT_FOCUS.rest, cycles: DEFAULT_FOCUS.cycles });
    expect(cleanConfig(null)).toEqual(DEFAULT_FOCUS);
    expect(cleanConfig({ work: Number.NaN })).toEqual(DEFAULT_FOCUS);
  });

  it('diz ao Jarvis como a sessão está', () => {
    const focus = startFocus({ work: 25, rest: 5, cycles: 4 }, T0);
    expect(focusReport(focus, T0 + MIN)).toEqual({ running: true, phase: 'work', cycle: 1, cycles: 4, remaining_s: 1440 });
    expect(focusReport(IDLE_FOCUS, T0)).toMatchObject({ running: false, remaining_s: 0 });
  });

  it('formata a contagem', () => {
    expect(formatCountdown(1500)).toBe('25:00');
    expect(formatCountdown(65)).toBe('01:05');
    expect(formatCountdown(0)).toBe('00:00');
    expect(formatCountdown(7200)).toBe('120:00');
  });
});

describe('sessão salva no navegador', () => {
  it('volta de onde parou depois de recarregar', () => {
    const focus = { ...startFocus({ work: 30, rest: 10, cycles: 3 }, T0), phase: 'rest' as const, cycle: 2 };
    expect(parseFocus(JSON.stringify(focus))).toEqual(focus);
  });

  it('ignora lixo e mantém as preferências de uma sessão parada', () => {
    expect(parseFocus(null)).toEqual(IDLE_FOCUS);
    expect(parseFocus('{quebrado')).toEqual(IDLE_FOCUS);
    expect(parseFocus(JSON.stringify({ running: true, endsAt: 'amanhã' })).running).toBe(false);
    expect(parseFocus(JSON.stringify({ running: false, work: 50, rest: 10, cycles: 2 }))).toMatchObject({ running: false, work: 50, rest: 10, cycles: 2 });
    expect(parseFocus(JSON.stringify({ running: true, endsAt: T0, cycle: 99, cycles: 4 })).cycle).toBe(4);
  });
});
