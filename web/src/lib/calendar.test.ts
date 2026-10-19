import { describe, expect, it } from 'vitest';
import { calendarDetail, eventClock, eventTime, groupByDay, isOngoing } from './calendar';
import { trimCards } from './hudStore';
import { matchPanels } from './panels';
import type { CalendarData, CalendarEvent, HudCard } from './types';
import { hasPendingWork } from './wake';

const daily: CalendarEvent = {
  id: 'e1',
  title: 'Daily',
  start: '2026-10-19T09:00:00-03:00',
  end: '2026-10-19T09:15:00-03:00',
  all_day: false,
};
const birthday: CalendarEvent = { id: 'e2', title: 'Aniversário da Ana', start: '2026-10-20T00:00:00-03:00', end: '2026-10-21T00:00:00-03:00', all_day: true };
const agenda: CalendarData = { status: 'agenda', label: 'hoje (segunda, 19 de outubro)', date: '2026-10-19', events: [daily] };
const pending: CalendarData = {
  status: 'pending',
  label: 'sexta, 23 de outubro',
  date: '2026-10-23',
  events: [],
  action: 'create',
  code: '482913',
  pending: { title: 'Dentista', when: 'sexta, 23 de outubro, 15:00–16:00' },
};

describe('calendar panel', () => {
  it('shows the São Paulo time from the ISO text, whatever the browser timezone', () => {
    expect(eventClock('2026-10-19T09:00:00-03:00')).toBe('09:00');
    expect(eventTime(daily)).toBe('09:00–09:15');
    expect(eventTime(birthday)).toBe('dia inteiro');
  });

  it('groups a multi-day listing by day', () => {
    expect(groupByDay([daily, birthday]).map((group) => group.day)).toEqual(['2026-10-19', '2026-10-20']);
  });

  it('knows which meeting is happening now', () => {
    expect(isOngoing(daily, Date.parse('2026-10-19T09:05:00-03:00'))).toBe(true);
    expect(isOngoing(daily, Date.parse('2026-10-19T09:15:00-03:00'))).toBe(false);
    expect(isOngoing(birthday, Date.parse('2026-10-20T10:00:00-03:00'))).toBe(false);
  });

  it('describes the panel for the agent', () => {
    expect(calendarDetail(agenda)).toBe('hoje (segunda, 19 de outubro) · 1 evento');
    expect(calendarDetail(pending)).toBe('Dentista · aguardando código');
    expect(calendarDetail({ ...agenda, status: 'created', message: 'Criar: Dentista' })).toBe('Criar: Dentista · Evento criado');
  });

  it('keeps a change waiting for its code on screen and the link open', () => {
    const cards: HudCard[] = [{ id: 'cal', kind: 'calendar', data: pending, createdAt: 0 }];
    for (let index = 1; index <= 8; index++) {
      cards.unshift({ id: `n${index}`, kind: 'search', data: { query: `q${index}`, results: [] }, createdAt: index });
    }
    expect(trimCards(cards).some((card) => card.id === 'cal')).toBe(true);
    expect(hasPendingWork([{ id: 'cal', kind: 'calendar', data: pending, createdAt: 0 }], 0)).toBe(true);
    expect(hasPendingWork([{ id: 'cal', kind: 'calendar', data: agenda, createdAt: 0 }], 0)).toBe(false);
  });

  it('answers to "fecha a agenda" and "a aba das reuniões"', () => {
    const cards: HudCard[] = [{ id: 'cal', kind: 'calendar', data: agenda, createdAt: 1 }];
    expect(matchPanels(cards, ['agenda']).matched.map((card) => card.id)).toEqual(['cal']);
    expect(matchPanels(cards, ['reunioes']).matched.map((card) => card.id)).toEqual(['cal']);
  });
});
