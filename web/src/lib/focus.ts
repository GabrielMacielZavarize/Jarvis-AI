/**
 * Sessão de foco (FOC-47): blocos de trabalho e pausas, no estilo Pomodoro. A fonte da verdade é o
 * servidor do HUD (`focus.py`): ele conta com a aba fechada, pausa quando você sai da frente do PC e
 * avisa a troca de bloco. Aqui ficam o espelho do estado (para o anel e o chip do topo), os
 * comandos e o aviso de som e notificação quando a aba está aberta.
 */
import { create } from 'zustand';
import { useHud } from './hudStore';
import { playCue } from './sounds';

export type FocusPhase = 'work' | 'rest';
/** O que o servidor registra a cada troca: blocos, pausa pela ausência e volta. */
export type FocusEventKind = 'rest' | 'work' | 'done' | 'paused' | 'resumed';

export interface FocusConfig {
  /** Minutos de cada bloco de foco. */
  work: number;
  /** Minutos de cada pausa. */
  rest: number;
  /** Quantos blocos de foco. */
  cycles: number;
}

export interface FocusState extends FocusConfig {
  running: boolean;
  phase: FocusPhase;
  /** Bloco de foco atual, de 1 a `cycles`. */
  cycle: number;
  /** A contagem parou porque você saiu da frente do PC (presença ligada). */
  paused: boolean;
  /** Quando o bloco atual termina, no relógio deste navegador (ms). 0 parado ou pausado. */
  endsAt: number;
  /** Quanto faltava ao pausar (s). Só vale com `paused`. */
  pausedRemaining: number;
}

/** A última troca registrada pelo servidor (`last_event` de `/api/focus`). */
export interface FocusLastEvent {
  seq: number;
  kind: FocusEventKind;
  title: string;
  message: string;
  /** Relógio do servidor (ms). */
  at_ms: number;
}

export const DEFAULT_FOCUS: FocusConfig = { work: 25, rest: 5, cycles: 4 };
export const FOCUS_LIMITS = { work: [1, 180], rest: [1, 60], cycles: [1, 12] } as const;
export const FOCUS_POLL_MS = 3000;
export const IDLE_FOCUS: FocusState = { ...DEFAULT_FOCUS, running: false, phase: 'work', cycle: 1, paused: false, endsAt: 0, pausedRemaining: 0 };

const EVENT_KINDS: readonly FocusEventKind[] = ['rest', 'work', 'done', 'paused', 'resumed'];

function clamp(value: unknown, [low, high]: readonly [number, number], fallback: number): number {
  const number = typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : fallback;
  return Math.max(low, Math.min(high, number));
}

export function cleanConfig(raw: Partial<FocusConfig> | null | undefined): FocusConfig {
  return {
    work: clamp(raw?.work, FOCUS_LIMITS.work, DEFAULT_FOCUS.work),
    rest: clamp(raw?.rest, FOCUS_LIMITS.rest, DEFAULT_FOCUS.rest),
    cycles: clamp(raw?.cycles, FOCUS_LIMITS.cycles, DEFAULT_FOCUS.cycles),
  };
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/**
 * O estado de `/api/focus` no relógio deste navegador: o servidor manda o horário dele (`now_ms`) e o
 * do fim do bloco, e a diferença entre os dois relógios sai da conta. null se a resposta não for isso.
 */
export function stateFromSnapshot(raw: unknown, clientNow: number): FocusState | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const data = raw as Record<string, unknown>;
  if (data.enabled === false || typeof data.running !== 'boolean') return null;
  const config = cleanConfig(data as Partial<FocusConfig>);
  if (!data.running) return { ...IDLE_FOCUS, ...config };
  const paused = data.paused === true;
  const skew = isNumber(data.now_ms) ? data.now_ms - clientNow : 0;
  const endsAt = isNumber(data.ends_at_ms) ? data.ends_at_ms - skew : 0;
  if (!paused && endsAt <= 0) return null;
  return {
    ...config,
    running: true,
    phase: data.phase === 'rest' ? 'rest' : 'work',
    cycle: clamp(data.cycle, [1, config.cycles], 1),
    paused,
    endsAt: paused ? 0 : endsAt,
    pausedRemaining: paused && isNumber(data.remaining_s) ? Math.max(0, data.remaining_s) : 0,
  };
}

export function lastEventOf(raw: unknown): FocusLastEvent | null {
  const event = (raw as { last_event?: unknown } | null)?.last_event;
  if (typeof event !== 'object' || event === null) return null;
  const data = event as Record<string, unknown>;
  if (!EVENT_KINDS.includes(data.kind as FocusEventKind) || !isNumber(data.at_ms) || typeof data.title !== 'string') return null;
  return {
    seq: isNumber(data.seq) ? data.seq : 0,
    kind: data.kind as FocusEventKind,
    title: data.title,
    message: typeof data.message === 'string' ? data.message : '',
    at_ms: data.at_ms,
  };
}

export function remainingSeconds(state: FocusState, now: number): number {
  if (!state.running) return 0;
  if (state.paused) return Math.ceil(state.pausedRemaining);
  return Math.max(0, Math.ceil((state.endsAt - now) / 1000));
}

/** 0 → 1 do bloco atual, para o anel de progresso. */
export function phaseProgress(state: FocusState, now: number): number {
  if (!state.running) return 0;
  const total = (state.phase === 'work' ? state.work : state.rest) * 60;
  return Math.max(0, Math.min(1, 1 - remainingSeconds(state, now) / total));
}

export function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

/** Já passou do fim do bloco e o servidor ainda não mandou a troca (ele conta a cada segundo). */
export function blockEnded(state: FocusState, now: number): boolean {
  return state.running && !state.paused && now >= state.endsAt;
}

/** Som, notificação e registro de cada troca vista com a aba aberta. */
function announce(event: FocusLastEvent) {
  const hud = useHud.getState();
  if (event.kind === 'paused') {
    hud.addLog('info', 'Foco · pausado porque você saiu');
    return;
  }
  playCue('timerDone');
  const level = event.kind === 'work' || event.kind === 'resumed' ? 'info' : 'warn';
  hud.pushToast({ level, title: event.title, message: event.message, code: 'FOC-47' });
  hud.addLog(event.kind === 'done' ? 'ok' : 'info', `Foco · ${event.title.toLowerCase()}`);
}

interface FocusStore {
  focus: FocusState;
  /** Por que o último comando não deu certo (o servidor fora do ar, o foco desligado). */
  error: string | null;
  /** Lê o servidor. Chamado a cada poucos segundos e quando o bloco passa do fim. */
  sync: () => Promise<void>;
  start: (config?: Partial<FocusConfig>) => Promise<void>;
  stop: () => Promise<void>;
  skip: () => Promise<void>;
}

// A troca de bloco só vira aviso depois da primeira leitura: abrir ou recarregar a aba não repete
// o que o servidor já avisou (pela bandeja ou pela voz).
let lastEventAt: number | null = null;
let inFlight = false;

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { cache: 'no-store', ...init, headers: init?.body ? { 'Content-Type': 'application/json' } : undefined });
  if (!response.ok) {
    let detail = `O servidor respondeu ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // Sem corpo JSON: fica a mensagem genérica.
    }
    throw new Error(detail);
  }
  return response.json();
}

export const useFocus = create<FocusStore>((set, get) => {
  const apply = (raw: unknown) => {
    const focus = stateFromSnapshot(raw, Date.now());
    if (!focus) return;
    const event = lastEventOf(raw);
    if (lastEventAt === null) lastEventAt = event?.at_ms ?? 0;
    else if (event && event.at_ms > lastEventAt) {
      lastEventAt = event.at_ms;
      announce(event);
    }
    set({ focus, error: null });
  };

  const command = async (body: Record<string, unknown>): Promise<boolean> => {
    try {
      apply(await request('/api/focus', { method: 'POST', body: JSON.stringify(body) }));
      return true;
    } catch (error) {
      set({ error: error instanceof Error && error.message ? error.message : 'O servidor do HUD não respondeu.' });
      return false;
    }
  };

  return {
    focus: IDLE_FOCUS,
    error: null,
    sync: async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        apply(await request('/api/focus'));
      } catch {
        // Sem servidor a tela segue com o último estado; a próxima leitura tenta de novo.
      } finally {
        inFlight = false;
      }
    },
    start: async (config) => {
      const clean = cleanConfig(config ?? get().focus);
      if (await command({ command: 'start', ...clean })) {
        useHud.getState().addLog('info', `Foco iniciado · ${clean.cycles}×${clean.work} min`);
      }
    },
    stop: async () => void (await command({ command: 'stop' })),
    skip: async () => void (await command({ command: 'skip' })),
  };
});

/** Só para os testes: volta ao estado de uma aba recém-aberta. */
export function resetFocusForTests() {
  lastEventAt = null;
  inFlight = false;
  useFocus.setState({ focus: IDLE_FOCUS, error: null });
}
