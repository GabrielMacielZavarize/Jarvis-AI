import type { DictationEvent, DictationState } from './types';

/** How long the indicator stays after dictation ends (or after a one-shot "escreve aqui"). */
export const DICTATION_LINGER_MS = 4000;
const TAIL_LIMIT = 160;

/** Next indicator state for a dictation event from the agent. */
export function reduceDictation(prev: DictationState | null, event: DictationEvent, now: number): DictationState {
  const fresh = event.state === 'on' || event.state === 'once' || !prev;
  const typed = event.typed ?? '';
  return {
    active: event.active,
    phase: event.state,
    tail: (event.tail ?? prev?.tail ?? '').slice(-TAIL_LIMIT),
    typed: event.state === 'typing' || event.state === 'once' ? typed : '',
    heard: event.heard ?? (fresh ? '' : (prev?.heard ?? '')),
    message: event.message ?? '',
    commands: event.commands ?? [],
    caps: event.caps ?? false,
    window: event.window ?? prev?.window ?? null,
    chars: (fresh ? 0 : (prev?.chars ?? 0)) + typed.length,
    updatedAt: now,
  };
}

/** Keep showing it? Always while active; for a few seconds after it ends. */
export function dictationVisible(state: DictationState | null, now: number): boolean {
  if (!state) return false;
  return state.active || now - state.updatedAt < DICTATION_LINGER_MS;
}

/** The tail split so the piece just typed can be highlighted. */
export function splitTail(state: DictationState): { before: string; typed: string } {
  const typed = state.typed.trim() ? state.typed : '';
  if (typed && state.tail.endsWith(typed)) return { before: state.tail.slice(0, -typed.length), typed };
  return { before: state.tail, typed: '' };
}

/** Log line for the activity panel. */
export function dictationLog(event: DictationEvent): { level: 'ok' | 'warn' | 'info'; text: string } | null {
  if (event.state === 'on') return { level: 'ok', text: `DIT-29 · ditado ligado${event.window ? ` em ${event.window}` : ''}` };
  if (event.state === 'off') return { level: 'info', text: `DIT-29 · ${event.message ?? 'ditado desligado'}` };
  if (event.state === 'warn') return { level: 'warn', text: `DIT-29 · ${event.message ?? 'aviso'}` };
  if (event.state === 'once') return { level: 'ok', text: `DIT-29 · ${event.message ?? 'texto escrito'}` };
  return null;
}
