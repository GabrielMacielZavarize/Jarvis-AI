import type { CalendarData, CalendarEvent } from './types';

export const CALENDAR_STATUS: Record<CalendarData['status'], [string, string]> = {
  agenda: ['Google Agenda', 'status-chip--off'],
  pending: ['Aguardando confirmação', 'status-chip--warn'],
  created: ['Evento criado', 'status-chip--ok'],
  updated: ['Evento alterado', 'status-chip--ok'],
  deleted: ['Evento apagado', 'status-chip--ok'],
  cancelled: ['Mudança cancelada', 'status-chip--off'],
};

export const CALENDAR_ACTIONS: Record<NonNullable<CalendarData['action']>, string> = {
  create: 'Novo evento',
  update: 'Alterar evento',
  delete: 'Apagar evento',
};

/**
 * "2026-10-23T15:00:00-03:00" → "15:00". Read straight from the ISO text, so the HUD shows the
 * São Paulo time the agent sent even when the browser is in another timezone.
 */
export function eventClock(iso: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  return match ? `${match[1]}:${match[2]}` : '';
}

export function eventTime(event: CalendarEvent): string {
  if (event.all_day) return 'dia inteiro';
  return `${eventClock(event.start)}–${eventClock(event.end)}`;
}

/** The ISO date (YYYY-MM-DD) an event starts on, in the agent's timezone. */
function eventDay(event: CalendarEvent): string {
  return event.start.slice(0, 10);
}

/** Events grouped by day (a multi-day listing like "essa semana"), in order. */
export function groupByDay(events: CalendarEvent[]): { day: string; events: CalendarEvent[] }[] {
  const groups: { day: string; events: CalendarEvent[] }[] = [];
  for (const event of events) {
    const day = eventDay(event);
    const last = groups[groups.length - 1];
    if (last?.day === day) last.events.push(event);
    else groups.push({ day, events: [event] });
  }
  return groups;
}

/** Event happening at `now` (ms). */
export function isOngoing(event: CalendarEvent, now: number): boolean {
  if (event.all_day) return false;
  return Date.parse(event.start) <= now && now < Date.parse(event.end);
}

/** Subtitle of the panel in the list the agent gets ("hoje (segunda, 19 de outubro) · 3 eventos"). */
export function calendarDetail(data: CalendarData): string {
  if (data.status === 'pending' && data.pending) return `${data.pending.title} · aguardando código`;
  if (data.status !== 'agenda') return [data.message, CALENDAR_STATUS[data.status][0]].filter(Boolean).join(' · ');
  const count = data.events.length;
  return `${data.label} · ${count} ${count === 1 ? 'evento' : 'eventos'}`;
}
