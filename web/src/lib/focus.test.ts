import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  blockEnded,
  cleanConfig,
  DEFAULT_FOCUS,
  formatCountdown,
  IDLE_FOCUS,
  lastEventOf,
  phaseProgress,
  remainingSeconds,
  resetFocusForTests,
  stateFromSnapshot,
  useFocus,
} from './focus';
import { useHud } from './hudStore';
import { noticeIsShownByHud } from './wake';

const T0 = 1_800_000_000_000;

/** O que `/api/focus` devolve com um bloco de foco de 25 min a meio caminho. */
const running = (extra: Record<string, unknown> = {}) => ({
  enabled: true,
  running: true,
  phase: 'work',
  cycle: 1,
  cycles: 4,
  work: 25,
  rest: 5,
  paused: false,
  paused_reason: null,
  remaining_s: 900,
  ends_at_ms: T0 + 900_000,
  now_ms: T0,
  last_event: null,
  ...extra,
});

describe('estado vindo do servidor', () => {
  it('conta o fim do bloco no relógio deste navegador, mesmo com os relógios diferentes', () => {
    // O relógio do servidor está 2 minutos na frente do do navegador.
    const state = stateFromSnapshot(running({ now_ms: T0 + 120_000, ends_at_ms: T0 + 120_000 + 900_000 }), T0);
    expect(state).toMatchObject({ running: true, phase: 'work', cycle: 1, cycles: 4, paused: false, endsAt: T0 + 900_000 });
    expect(remainingSeconds(state!, T0)).toBe(900);
    expect(remainingSeconds(state!, T0 + 899_500)).toBe(1);
    expect(remainingSeconds(state!, T0 + 2_000_000)).toBe(0);
    expect(phaseProgress(state!, T0)).toBeCloseTo(1 - 900 / 1500);
    expect(blockEnded(state!, T0 + 899_000)).toBe(false);
    expect(blockEnded(state!, T0 + 900_000)).toBe(true);
  });

  it('pausada pela ausência, congela a contagem e o anel', () => {
    const state = stateFromSnapshot(running({ paused: true, paused_reason: 'away', ends_at_ms: null, remaining_s: 600 }), T0)!;
    expect(state).toMatchObject({ running: true, paused: true, endsAt: 0, pausedRemaining: 600 });
    expect(remainingSeconds(state, T0)).toBe(600);
    expect(remainingSeconds(state, T0 + 3_600_000)).toBe(600);
    expect(phaseProgress(state, T0 + 3_600_000)).toBeCloseTo(0.6);
    expect(blockEnded(state, T0 + 3_600_000)).toBe(false);
  });

  it('sessão parada guarda só os tempos para o painel', () => {
    const state = stateFromSnapshot({ enabled: true, running: false, work: 50, rest: 10, cycles: 2, paused: false, remaining_s: 0, ends_at_ms: null, now_ms: T0, last_event: null }, T0);
    expect(state).toEqual({ ...IDLE_FOCUS, work: 50, rest: 10, cycles: 2 });
    expect(remainingSeconds(state!, T0)).toBe(0);
    expect(phaseProgress(state!, T0)).toBe(0);
  });

  it('ignora o que não é uma sessão: foco desligado, lixo, bloco sem fim', () => {
    expect(stateFromSnapshot({ enabled: false }, T0)).toBeNull();
    expect(stateFromSnapshot(null, T0)).toBeNull();
    expect(stateFromSnapshot('quebrado', T0)).toBeNull();
    expect(stateFromSnapshot(running({ ends_at_ms: null }), T0)).toBeNull();
    expect(stateFromSnapshot(running({ cycle: 99 }), T0)?.cycle).toBe(4);
  });

  it('segura os valores dentro dos limites', () => {
    expect(cleanConfig({ work: 0, rest: 999, cycles: -3 })).toEqual({ work: 1, rest: 60, cycles: 1 });
    expect(cleanConfig({ work: 50.4 })).toEqual({ work: 50, rest: DEFAULT_FOCUS.rest, cycles: DEFAULT_FOCUS.cycles });
    expect(cleanConfig(null)).toEqual(DEFAULT_FOCUS);
    expect(cleanConfig({ work: Number.NaN })).toEqual(DEFAULT_FOCUS);
  });

  it('lê a última troca registrada', () => {
    const event = { seq: 3, kind: 'rest', title: 'Hora da pausa', message: 'Bloco 1 de 4 concluído.', at_ms: T0 };
    expect(lastEventOf({ last_event: event })).toEqual(event);
    expect(lastEventOf({ last_event: { ...event, kind: 'dançar' } })).toBeNull();
    expect(lastEventOf({ last_event: { ...event, at_ms: 'ontem' } })).toBeNull();
    expect(lastEventOf({ last_event: null })).toBeNull();
    expect(lastEventOf(null)).toBeNull();
  });

  it('formata a contagem', () => {
    expect(formatCountdown(1500)).toBe('25:00');
    expect(formatCountdown(65)).toBe('01:05');
    expect(formatCountdown(0)).toBe('00:00');
    expect(formatCountdown(7200)).toBe('120:00');
  });
});

describe('a troca de bloco do foco não aparece duas vezes', () => {
  it('o aviso do motor (voz e bandeja) não vira cartão nem notificação no HUD', () => {
    expect(noticeIsShownByHud({ topic: 'focus' })).toBe(false);
    expect(noticeIsShownByHud({ topic: 'battery' })).toBe(true);
  });
});

describe('espelho do servidor', () => {
  const calls: { path: string; method: string; body: unknown }[] = [];
  let reply: unknown;

  beforeEach(() => {
    calls.length = 0;
    reply = running();
    resetFocusForTests();
    useHud.setState({ toasts: [], log: [] });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
        return { ok: true, status: 200, json: async () => reply } as Response;
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  const toastTitles = () => useHud.getState().toasts.map((toast) => toast.title);

  it('lê o servidor e mostra a sessão que a voz começou', async () => {
    expect(useFocus.getState().focus.running).toBe(false);
    await useFocus.getState().sync();
    expect(calls[0]).toMatchObject({ path: '/api/focus', method: 'GET' });
    expect(useFocus.getState().focus).toMatchObject({ running: true, cycles: 4 });
  });

  it('começar, pular e encerrar mandam o comando ao servidor e mostram a resposta', async () => {
    await useFocus.getState().start({ work: 10, rest: 2, cycles: 2 });
    expect(calls[0]).toEqual({ path: '/api/focus', method: 'POST', body: { command: 'start', work: 10, rest: 2, cycles: 2 } });
    reply = running({ phase: 'rest', remaining_s: 300, ends_at_ms: T0 + 300_000 });
    await useFocus.getState().skip();
    expect(calls[1].body).toEqual({ command: 'skip' });
    expect(useFocus.getState().focus.phase).toBe('rest');
    reply = { enabled: true, running: false, work: 10, rest: 2, cycles: 2, paused: false, remaining_s: 0, ends_at_ms: null, now_ms: T0, last_event: null };
    await useFocus.getState().stop();
    expect(calls[2].body).toEqual({ command: 'stop' });
    expect(useFocus.getState().focus.running).toBe(false);
  });

  it('sem tempos, "começar" repete os do painel', async () => {
    useFocus.setState({ focus: { ...IDLE_FOCUS, work: 50, rest: 10, cycles: 3 } });
    await useFocus.getState().start();
    expect(calls[0].body).toEqual({ command: 'start', work: 50, rest: 10, cycles: 3 });
  });

  it('avisa com notificação só a troca que acontece depois da primeira leitura', async () => {
    const old = { seq: 1, kind: 'rest', title: 'Hora da pausa', message: 'Bloco 1 de 4 concluído.', at_ms: T0 - 60_000 };
    reply = running({ last_event: old });
    await useFocus.getState().sync();
    // Recarregar a aba não repete o que o servidor já avisou.
    expect(toastTitles()).toEqual([]);

    reply = running({ phase: 'work', cycle: 2, last_event: { seq: 2, kind: 'work', title: 'De volta ao foco', message: 'Bloco 2 de 4: 25 min.', at_ms: T0 } });
    await useFocus.getState().sync();
    expect(toastTitles()).toEqual(['De volta ao foco']);
    // A mesma troca lida de novo não vira outro aviso.
    await useFocus.getState().sync();
    expect(toastTitles()).toEqual(['De volta ao foco']);
  });

  it('a pausa pela ausência só entra no registro; a volta avisa', async () => {
    await useFocus.getState().sync();
    reply = running({ paused: true, ends_at_ms: null, last_event: { seq: 5, kind: 'paused', title: 'Foco pausado', message: 'Você saiu.', at_ms: T0 + 1 } });
    await useFocus.getState().sync();
    expect(toastTitles()).toEqual([]);
    expect(useHud.getState().log.map((entry) => entry.text)).toContain('Foco · pausado porque você saiu');
    reply = running({ last_event: { seq: 6, kind: 'resumed', title: 'Foco retomado', message: 'Faltam 14 min.', at_ms: T0 + 2 } });
    await useFocus.getState().sync();
    expect(toastTitles()).toEqual(['Foco retomado']);
  });

  it('com o servidor fora do ar, o comando mostra o erro e o estado fica como estava', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403, json: async () => ({ detail: 'O foco está desligado.' }) }) as Response));
    await useFocus.getState().start();
    expect(useFocus.getState().error).toBe('O foco está desligado.');
    expect(useFocus.getState().focus.running).toBe(false);
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('fetch failed'))));
    await useFocus.getState().stop();
    expect(useFocus.getState().error).toBe('fetch failed');
  });
});
