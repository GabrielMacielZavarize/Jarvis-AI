/**
 * Sessão de foco (FOC-47): blocos de trabalho e pausas, no estilo Pomodoro. Roda no HUD, não no
 * agente, para a contagem continuar depois que o link fecha por silêncio; fica salva no navegador,
 * então recarregar a página não zera o bloco em andamento.
 */
import { create } from 'zustand';
import { useHud } from './hudStore';
import { playCue } from './sounds';

export type FocusPhase = 'work' | 'rest';
export type FocusEvent = 'rest' | 'work' | 'done';

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
  /** Quando o bloco atual termina (ms). */
  endsAt: number;
}

export const DEFAULT_FOCUS: FocusConfig = { work: 25, rest: 5, cycles: 4 };
export const FOCUS_LIMITS = { work: [1, 180], rest: [1, 60], cycles: [1, 12] } as const;
export const FOCUS_STORAGE_KEY = 'jarvis.focus';
export const IDLE_FOCUS: FocusState = { ...DEFAULT_FOCUS, running: false, phase: 'work', cycle: 1, endsAt: 0 };

const MINUTE = 60_000;

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

export function startFocus(config: Partial<FocusConfig>, now: number): FocusState {
  const clean = cleanConfig(config);
  return { ...clean, running: true, phase: 'work', cycle: 1, endsAt: now + clean.work * MINUTE };
}

/** O bloco seguinte, contado a partir de `from` (o fim do anterior, ou agora ao pular). */
function nextBlock(state: FocusState, from: number): { state: FocusState; event: FocusEvent } {
  if (state.phase === 'work') {
    // Depois do último bloco de foco não há pausa: a sessão acabou.
    if (state.cycle >= state.cycles) return { state: { ...state, running: false, endsAt: 0 }, event: 'done' };
    return { state: { ...state, phase: 'rest', endsAt: from + state.rest * MINUTE }, event: 'rest' };
  }
  return { state: { ...state, phase: 'work', cycle: state.cycle + 1, endsAt: from + state.work * MINUTE }, event: 'work' };
}

/**
 * Anda a sessão até `now`. Se a aba dormiu por vários blocos, passa por todos de uma vez e devolve
 * cada troca que aconteceu, com os horários contados do fim de cada bloco (sem acumular atraso).
 */
export function advance(state: FocusState, now: number): { state: FocusState; events: FocusEvent[] } {
  const events: FocusEvent[] = [];
  let current = state;
  while (current.running && now >= current.endsAt && events.length < 64) {
    const step = nextBlock(current, current.endsAt);
    current = step.state;
    events.push(step.event);
  }
  return { state: current, events };
}

export function skipPhase(state: FocusState, now: number): { state: FocusState; events: FocusEvent[] } {
  if (!state.running) return { state, events: [] };
  const step = nextBlock(state, now);
  return { state: step.state, events: [step.event] };
}

export function remainingSeconds(state: FocusState, now: number): number {
  return state.running ? Math.max(0, Math.ceil((state.endsAt - now) / 1000)) : 0;
}

/** 0 → 1 do bloco atual, para o anel de progresso. */
export function phaseProgress(state: FocusState, now: number): number {
  if (!state.running) return 0;
  const total = (state.phase === 'work' ? state.work : state.rest) * MINUTE;
  return Math.max(0, Math.min(1, 1 - (state.endsAt - now) / total));
}

export function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

/** O que a ferramenta de voz recebe de volta. */
export function focusReport(state: FocusState, now: number) {
  return { running: state.running, phase: state.phase, cycle: state.cycle, cycles: state.cycles, remaining_s: remainingSeconds(state, now) };
}

export function parseFocus(raw: string | null): FocusState {
  if (!raw) return IDLE_FOCUS;
  try {
    const data = JSON.parse(raw) as Partial<FocusState>;
    const config = cleanConfig(data);
    if (!data.running || typeof data.endsAt !== 'number' || !Number.isFinite(data.endsAt)) return { ...IDLE_FOCUS, ...config };
    return {
      ...config,
      running: true,
      phase: data.phase === 'rest' ? 'rest' : 'work',
      cycle: clamp(data.cycle, [1, config.cycles], 1),
      endsAt: data.endsAt,
    };
  } catch {
    return IDLE_FOCUS;
  }
}

function load(): FocusState {
  try {
    return typeof window === 'undefined' ? IDLE_FOCUS : parseFocus(window.localStorage.getItem(FOCUS_STORAGE_KEY));
  } catch {
    return IDLE_FOCUS;
  }
}

function save(state: FocusState) {
  try {
    window.localStorage.setItem(FOCUS_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Janela anônima: a sessão vale até a aba fechar.
  }
}

const EVENT_TEXT: Record<FocusEvent, { title: string; message: (state: FocusState) => string }> = {
  rest: { title: 'Hora da pausa', message: (s) => `Bloco ${s.cycle} de ${s.cycles} concluído. ${s.rest} min de descanso.` },
  work: { title: 'De volta ao foco', message: (s) => `Bloco ${s.cycle} de ${s.cycles}: ${s.work} min.` },
  done: { title: 'Sessão de foco concluída', message: (s) => `${s.cycles} ${s.cycles === 1 ? 'bloco' : 'blocos'} de ${s.work} min. Bom trabalho.` },
};

/** Som, notificação e registro de cada troca de bloco. */
function announce(events: FocusEvent[], state: FocusState) {
  if (events.length === 0) return;
  const hud = useHud.getState();
  // Vários blocos de uma vez (aba que dormiu): só o último vira aviso.
  const event = events[events.length - 1];
  const text = EVENT_TEXT[event];
  playCue('timerDone');
  hud.pushToast({ level: event === 'work' ? 'info' : 'warn', title: text.title, message: text.message(state), code: 'FOC-47' });
  hud.addLog(event === 'done' ? 'ok' : 'info', `Foco · ${text.title.toLowerCase()}`);
}

interface FocusStore {
  focus: FocusState;
  start: (config?: Partial<FocusConfig>) => void;
  stop: () => void;
  skip: () => void;
  /** Chamado a cada segundo enquanto a sessão roda. */
  tick: (now?: number) => void;
}

export const useFocus = create<FocusStore>((set, get) => ({
  focus: load(),
  start: (config) => {
    const focus = startFocus(config ?? get().focus, Date.now());
    save(focus);
    set({ focus });
    useHud.getState().addLog('info', `Foco iniciado · ${focus.cycles}×${focus.work} min`);
  },
  stop: () => {
    const focus = { ...get().focus, running: false, endsAt: 0, phase: 'work' as const, cycle: 1 };
    save(focus);
    set({ focus });
  },
  skip: () => {
    const { state, events } = skipPhase(get().focus, Date.now());
    save(state);
    set({ focus: state });
    announce(events, state);
  },
  tick: (now = Date.now()) => {
    const current = get().focus;
    if (!current.running) return;
    const { state, events } = advance(current, now);
    if (events.length === 0) return;
    save(state);
    set({ focus: state });
    announce(events, state);
  },
}));
