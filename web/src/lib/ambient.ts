/** Ambient mode: what /api/ambient sends and how the idle screen words it. */

export interface AmbientWeather {
  city: string;
  temperature: number;
  code: number;
  label: string;
  is_day?: number;
  max?: number | null;
  min?: number | null;
}

export interface AmbientEvent {
  title: string;
  start: string;
  end: string;
  location?: string | null;
  call?: boolean;
}

export interface AmbientInfo {
  weather: AmbientWeather | null;
  next_event: AmbientEvent | null;
}

/** Idle time without a link before the ambient screen. */
export const AMBIENT_AFTER_MS = 3 * 60_000;
/** How often the ambient screen asks the server again (the server caches it too). */
export const AMBIENT_REFRESH_MS = 5 * 60_000;

export function parseAmbient(raw: unknown): AmbientInfo {
  const data = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const weather = data.weather as AmbientWeather | null | undefined;
  const event = data.next_event as AmbientEvent | null | undefined;
  return {
    weather: weather && typeof weather.temperature === 'number' ? weather : null,
    next_event: event && typeof event.title === 'string' && !Number.isNaN(Date.parse(event.start)) ? event : null,
  };
}

/** "agora", "em 25 min", "em 2 h 10", "amanhã às 09:00". */
export function untilEvent(event: AmbientEvent, now: number): string {
  const start = Date.parse(event.start);
  const end = Date.parse(event.end);
  if (start <= now && now < end) return 'agora';
  const minutes = Math.round((start - now) / 60_000);
  if (minutes < 60) return `em ${Math.max(1, minutes)} min`;
  const startDay = new Date(start).toDateString();
  if (startDay !== new Date(now).toDateString()) {
    return `amanhã às ${new Date(start).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `em ${hours} h ${String(rest).padStart(2, '0')}` : `em ${hours} h`;
}

/** Small shift every minute so a screen left on for hours does not burn the clock in. */
export function burnInOffset(now: number): { x: number; y: number } {
  const minute = Math.floor(now / 60_000);
  return { x: ((minute * 7) % 21) - 10, y: ((minute * 11) % 17) - 8 };
}
