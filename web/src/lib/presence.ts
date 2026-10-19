/** GET /api/presence (PRS-25): the webcam notices when the user arrives and leaves. */
export interface PresenceState {
  /** JARVIS_PRESENCE=true in the .env. */
  enabled: boolean;
  /** The detector is watching the webcam right now. */
  running: boolean;
  state: 'present' | 'away' | 'unknown' | 'off';
  /** Epoch seconds: arrival when present, departure when away. */
  since: number;
  /** Locks the PC after `away_minutes` away. */
  lock: boolean;
  away_minutes: number;
  /** A face is enrolled (python presence.py --enroll), so only the owner counts. */
  recognition: boolean;
  camera_off?: boolean;
  error: string | null;
}

export function parsePresence(raw: unknown): PresenceState | null {
  const data = raw as Partial<PresenceState> | null;
  if (!data || typeof data !== 'object' || typeof data.enabled !== 'boolean' || typeof data.state !== 'string') return null;
  return data as PresenceState;
}

/** "5 min", "1 h 20 min", "agora há pouco". */
export function awayFor(seconds: number): string {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (minutes < 1) return 'menos de 1 min';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** Text and tone of the Presença row of the Sistema panel. */
export function presenceLabel(presence: PresenceState, nowMs: number): { text: string; ok: boolean } {
  if (presence.camera_off) return { text: 'Câmera desligada · diga “liga a presença”', ok: false };
  if (presence.error) return { text: presence.error, ok: false };
  if (!presence.running) return { text: 'Desligada', ok: false };
  const lock = presence.lock ? ' · bloqueia ao sair' : '';
  if (presence.state === 'present') return { text: `Presente${presence.recognition ? ' · reconhecido' : ''}${lock}`, ok: true };
  if (presence.state === 'away') return { text: `Ausente há ${awayFor(nowMs / 1000 - presence.since)}${lock}`, ok: false };
  return { text: 'Verificando…', ok: false };
}
