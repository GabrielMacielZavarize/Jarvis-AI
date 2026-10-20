/**
 * GST-18 in the HUD: the Gestos panel. It shows what the hand-gesture engine is doing (events of
 * gestures.py over the data channel), edits what each free gesture does (gestos.json through
 * /api/gestures, with the same refusals as the voice) and turns things on and off through the
 * `jarvis.gestures` RPC while the agent is in the room.
 */
import type { CustomGesture, GestureBinding, GestureCatalog, GestureEvent, GestureLive, GestureState } from './types';

export const GESTURE_RPC_METHOD = 'jarvis.gestures';
/** Opening the webcam can take a while on Windows. */
const RPC_TIMEOUT_MS = 20_000;

export const INITIAL_GESTURES: GestureLive = { state: 'unknown', panel: false, holding: null, aim: null, last: null };

export const STATE_LABELS: Record<GestureState, string> = {
  unknown: 'Sem link',
  off: 'Desligados',
  idle: 'Desarmados',
  armed: 'Armados',
  grab: 'Segurando janela',
  close: 'Contando para fechar',
  mouse: 'Mouse no ar',
};

/** What the next event changes in the live state. */
export function reduceGesture(live: GestureLive, event: GestureEvent, now: number): GestureLive {
  switch (event.event) {
    case 'state':
      return {
        ...live,
        state: event.state,
        panel: event.state === 'off' ? false : live.panel,
        holding: event.state === 'armed' || event.state === 'mouse' ? live.holding : null,
        aim: null,
      };
    case 'grab':
      return { ...live, state: 'grab', holding: event.title ?? 'janela em foco', aim: null };
    case 'aim':
      return { ...live, aim: event.target ?? null };
    case 'cancel':
      return { ...live, state: live.state === 'grab' ? 'armed' : live.state, holding: null, aim: null, last: { text: 'Cancelado', ok: true, at: now } };
    case 'panel':
      return { ...live, panel: event.visible };
    case 'action':
      return {
        ...live,
        state: live.state === 'grab' || live.state === 'close' ? 'armed' : live.state,
        holding: null,
        aim: null,
        last: { text: event.message || event.action, ok: event.ok, at: now },
      };
  }
}

/** The reply of the panel's RPC: the service snapshot (gestures.py GestureService.snapshot). */
export interface GestureReply {
  ok: boolean;
  message: string;
  running: boolean;
  state: GestureState;
  panel: boolean;
  hand: boolean;
  fps: number;
  source: string;
  error: string | null;
}

const STATES = new Set<GestureState>(['off', 'idle', 'armed', 'grab', 'close', 'mouse']);

export function parseGestureReply(raw: string): GestureReply {
  const data = JSON.parse(raw) as Partial<GestureReply>;
  return {
    ok: data.ok === true,
    message: typeof data.message === 'string' ? data.message : '',
    running: data.running === true,
    state: data.state && STATES.has(data.state) ? data.state : 'off',
    panel: data.panel === true,
    hand: data.hand === true,
    fps: typeof data.fps === 'number' ? data.fps : 0,
    source: typeof data.source === 'string' ? data.source : '',
    error: typeof data.error === 'string' ? data.error : null,
  };
}

/** The live state after a reply (keeps the last action it already knew). */
export function liveFromReply(live: GestureLive, reply: GestureReply): GestureLive {
  return { ...live, state: reply.running ? reply.state : 'off', panel: reply.panel, holding: reply.state === 'grab' ? live.holding : null };
}

export type GestureAction = 'status' | 'on' | 'off' | 'arm' | 'mouse_on' | 'mouse_off' | 'panel_on' | 'panel_off';
type Transport = (payload: string, timeoutMs: number) => Promise<string>;

let transport: Transport | null = null;

/** Set by the live session while the agent is in the room; null when the link is down. */
export function setGestureTransport(next: Transport | null) {
  transport = next;
}

export function gestureLinkReady(): boolean {
  return transport !== null;
}

export async function gestureCommand(action: GestureAction): Promise<GestureReply> {
  if (!transport) throw new Error('Sem link com o Jarvis: abra o link para ligar os gestos pelo painel.');
  return parseGestureReply(await transport(JSON.stringify({ action }), RPC_TIMEOUT_MS));
}

// ───────────────────────── bindings (gestos.json) ─────────────────────────

/** Kinds the panel offers, in the server's words (GestureBindingRequest). */
export type BindingKind = 'action' | 'layout' | 'app' | 'site' | 'keys' | 'none';

export const KIND_LABELS: Record<BindingKind, string> = {
  action: 'Ação',
  layout: 'Layout',
  app: 'Abrir app',
  site: 'Abrir site',
  keys: 'Atalho',
  none: 'Nada',
};

const KIND_OF: Record<GestureBinding['tipo'], BindingKind> = {
  acao: 'action',
  layout: 'layout',
  app: 'app',
  site: 'site',
  atalho: 'keys',
  nada: 'none',
};

/** The editor's starting point for a gesture: its kind and value as the server stores them. */
export function editorValue(binding: GestureBinding): { kind: BindingKind; value: string } {
  const kind = KIND_OF[binding.tipo] ?? 'none';
  const value = binding.acao ?? binding.nome ?? binding.url ?? binding.teclas ?? '';
  return { kind, value };
}

export const KEY_PLACEHOLDERS: Partial<Record<BindingKind, string>> = {
  app: 'spotify, discord, notion…',
  site: 'youtube.com',
  keys: 'ctrl+shift+m',
};

export class GestureApiError extends Error {}

async function call(path: string, init?: RequestInit): Promise<GestureCatalog> {
  let response: Response;
  try {
    response = await fetch(path, { cache: 'no-store', ...init });
  } catch {
    throw new GestureApiError('Servidor do Jarvis fora do ar.');
  }
  const data = (await response.json().catch(() => null)) as (GestureCatalog & { detail?: string }) | null;
  if (!response.ok || !data) throw new GestureApiError(data?.detail || `Falha ${response.status} ao falar com o servidor.`);
  return data;
}

export function loadGestures(): Promise<GestureCatalog> {
  return call('/api/gestures');
}

export function saveGesture(id: string, kind: BindingKind, value: string): Promise<GestureCatalog> {
  return call(`/api/gestures/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, value: kind === 'none' ? null : value.trim() }),
  });
}

export function resetGesture(id: string | null): Promise<GestureCatalog> {
  return call(id ? `/api/gestures/${encodeURIComponent(id)}` : '/api/gestures', { method: 'DELETE' });
}

/** Emoji of each free gesture, for a compact list. */
export const GESTURE_GLYPHS: Record<string, string> = {
  ok: '👌',
  pinca_sobe: '🤏',
  pinca_desce: '🤏',
  rock: '🤘',
  joinha: '👍',
  tapar_camera: '✋',
  maos_afastam: '🙌',
  maos_aproximam: '🙌',
};

/** Name without the emoji the server puts in parentheses ("OK (👌)" → "OK"). */
export function plainName(gesture: CustomGesture): string {
  return gesture.name.replace(/\s*\([^)]*\)\s*$/, '');
}

/** "agora", "há 12 s", "há 3 min": how long ago the last gesture command ran. */
export function agoLabel(at: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 3) return 'agora';
  if (seconds < 60) return `há ${seconds} s`;
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `há ${minutes} min` : `há ${Math.round(minutes / 60)} h`;
}
