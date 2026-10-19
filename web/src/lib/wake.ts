import type { HudCard, JarvisMode, LogLevel, NoteData } from './types';

export type NoticePriority = 'low' | 'normal' | 'high' | 'critical';

/** PRO-28: a reminder or monitor speaking up. route: spoken now, opening the link, or HUD only. */
export interface NoticeEvent {
  type: 'notice';
  id: string;
  topic: string;
  priority: NoticePriority;
  title: string;
  message: string;
  route: 'speak' | 'wake' | 'hud';
}

/** Events of /api/wake/events (WAK-22, plus the PRO-28 notices). */
export type WakeEvent =
  | { type: 'config'; enabled: boolean; silence_s: number; proactive?: boolean }
  | { type: 'status'; detector: boolean; listening: boolean; mic_silent?: boolean }
  /** reason "notice": a proactive notice opens the link, not the user's voice. */
  | { type: 'wake'; score: number; reason?: 'notice' }
  | NoticeEvent;

export function parseWakeEvent(raw: string): WakeEvent | null {
  try {
    const event = JSON.parse(raw) as Partial<WakeEvent> | null;
    if (event?.type === 'notice') {
      return typeof event.title === 'string' && typeof event.message === 'string' ? (event as NoticeEvent) : null;
    }
    if (event?.type === 'config' || event?.type === 'status' || event?.type === 'wake') return event as WakeEvent;
  } catch {
    // A malformed line is ignored; the stream keeps going.
  }
  return null;
}

const VIRTUAL_IDS = new Set(['default', 'communications']);

/** Name of the microphone chosen in the Sistema panel for the detector, or null for the Windows default. */
export function micLabelFor(deviceId: string, devices: Pick<MediaDeviceInfo, 'deviceId' | 'label'>[]): string | null {
  if (VIRTUAL_IDS.has(deviceId)) return null;
  return devices.find((device) => device.deviceId === deviceId)?.label || null;
}

/**
 * Work that needs the link open: a timer Jarvis will announce out loud, a code waiting for
 * "confirmar …", or an install whose result he will report.
 */
export function hasPendingWork(cards: HudCard[], now: number): boolean {
  return cards.some((card) => {
    if (card.kind === 'timer') return card.data.status === 'running' && (card.data.ends_at == null || card.data.ends_at > now);
    if (card.kind === 'email') return card.data.status === 'draft';
    if (card.kind === 'install') return card.data.status === 'pending' || card.data.status === 'installing';
    return false;
  });
}

export interface SilenceInput {
  now: number;
  /** Last time anyone spoke, Jarvis thought or a tool ran. */
  lastActivityAt: number;
  silenceMs: number;
  mode: JarvisMode;
  pendingWork: boolean;
}

/** Jarvis is busy in these modes, so they count as activity. */
export const ACTIVE_MODES: ReadonlySet<JarvisMode> = new Set(['thinking', 'speaking']);

/**
 * Milliseconds until the link closes for silence, or null while it must stay open. A link still
 * waiting for the agent (or whose agent failed) also closes, so the detector gets the mic back.
 */
export function silenceLeft({ now, lastActivityAt, silenceMs, mode, pendingWork }: SilenceInput): number | null {
  if (silenceMs <= 0 || ACTIVE_MODES.has(mode) || pendingWork) return null;
  return Math.max(0, lastActivityAt + silenceMs - now);
}

/** The panel a notice opens on the HUD: one per subject, so a new battery notice replaces the last. */
export function noticeCard(notice: NoticeEvent): NoteData {
  const quiet = notice.route === 'hud' && notice.priority !== 'low' ? ' · sem voz' : '';
  return { title: `Aviso · ${notice.title}${quiet}`, content: notice.message };
}

export function noticeLogLevel(priority: NoticePriority): LogLevel {
  return priority === 'critical' || priority === 'high' ? 'warn' : 'info';
}
