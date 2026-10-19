import { useState } from 'react';
import { useClock } from '../../hooks/useClock';
import { CALENDAR_ACTIONS, CALENDAR_STATUS, eventTime, groupByDay, isOngoing } from '../../lib/calendar';
import { dayTimeline } from '../../lib/chart';
import { weekdayShort } from '../../lib/format';
import type { CalendarData, CalendarEvent } from '../../lib/types';
import { ConfirmCode } from './Cards';

function EventRow({ event, highlight, now }: { event: CalendarEvent; highlight: boolean; now: number }) {
  const ongoing = isOngoing(event, now);
  const classes = ['agd__item', highlight && 'agd__item--hl', ongoing && 'agd__item--now'].filter(Boolean).join(' ');
  return (
    <li className={classes}>
      <time className="agd__time">{eventTime(event)}</time>
      <div className="agd__text">
        <span className="agd__title">{event.title}</span>
        {(event.location || event.link) && (
          <span className="agd__meta">
            {ongoing ? 'agora · ' : ''}
            {event.link ? 'videochamada' : event.location}
          </span>
        )}
      </div>
    </li>
  );
}

/** "…T09:00:00-03:00" → "-03:00": the day is drawn in the agent's timezone, not the browser's. */
const offsetOf = (iso: string) => /([+-]\d{2}:\d{2}|Z)$/.exec(iso)?.[1] ?? 'Z';

/** The day as a strip of hours: each event a block (overlaps on a second lane) and a "now" mark. */
function DayTimeline({ date, events, highlight, now }: { date: string; events: CalendarEvent[]; highlight?: string | null; now: number }) {
  const timed = events.filter((event) => !event.all_day);
  const dayStart = Date.parse(`${date}T00:00:00${offsetOf(timed[0].start)}`);
  const { from, to, blocks } = dayTimeline(
    timed.map((event) => ({ item: event, start: Date.parse(event.start), end: Date.parse(event.end) })),
    dayStart,
  );
  const upcoming = timed.find((event) => Date.parse(event.end) > now) ?? timed[timed.length - 1];
  const [focus, setFocus] = useState<CalendarEvent | null>(null);
  const shown = focus ?? upcoming;
  const lanes = Math.max(...blocks.map((block) => block.lane)) + 1;
  const nowAt = (now - dayStart) / 3_600_000;
  const hours = Array.from({ length: to - from + 1 }, (_, index) => from + index).filter((hour) => (hour - from) % 3 === 0);

  return (
    <div className="agd-line">
      <div className="agd-line__track" style={{ height: lanes * 18 + 4 }} onPointerLeave={() => setFocus(null)}>
        {blocks.map((block) => (
          <button
            key={`${block.item.id}-${block.item.start}`}
            type="button"
            className={`agd-line__block ${block.item.id === highlight ? 'agd-line__block--hl' : ''} ${isOngoing(block.item, now) ? 'agd-line__block--now' : ''}`}
            style={{ left: `${block.left * 100}%`, width: `${block.width * 100}%`, top: block.lane * 18 + 2 }}
            onPointerEnter={() => setFocus(block.item)}
            onFocus={() => setFocus(block.item)}
            onBlur={() => setFocus(null)}
            aria-label={`${eventTime(block.item)} ${block.item.title}`}
          />
        ))}
        {nowAt >= from && nowAt <= to && (
          <i className="agd-line__now" style={{ left: `${((nowAt - from) / (to - from)) * 100}%` }} title="Agora" />
        )}
      </div>
      <div className="agd-line__hours" aria-hidden>
        {hours.map((hour) => (
          <span key={hour} style={{ left: `${((hour - from) / (to - from)) * 100}%` }}>
            {hour}h
          </span>
        ))}
      </div>
      {shown && (
        <div className="agd-line__readout">
          <time>{eventTime(shown)}</time> {shown.title}
        </div>
      )}
    </div>
  );
}

/** AGD-27: the day's Google Calendar, or the change Jarvis prepared and its confirmation code. */
export function CalendarBody({ data }: { data: CalendarData }) {
  const now = useClock(30_000);
  const [label, tone] = CALENDAR_STATUS[data.status];
  const groups = groupByDay(data.events);
  const severalDays = groups.length > 1;

  return (
    <div className="agd">
      <div className="agd__head">
        <span className={`status-chip ${tone}`}>{label}</span>
        <span className="card__sub">{data.label}</span>
      </div>
      {data.message && <div className="agd__message">{data.message}</div>}
      {data.status === 'agenda' && !severalDays && data.events.some((event) => !event.all_day) && (
        <DayTimeline date={data.date} events={data.events} highlight={data.highlight} now={now} />
      )}
      {data.status === 'pending' && data.pending && (
        <dl className="mail">
          <div>
            <dt>{CALENDAR_ACTIONS[data.action ?? 'create'].toUpperCase()}</dt>
            <dd>{data.pending.title}</dd>
          </div>
          {data.pending.before && (
            <div>
              <dt>ANTES</dt>
              <dd className="mail__address">{data.pending.before}</dd>
            </div>
          )}
          <div>
            <dt>{data.action === 'delete' ? 'EVENTO' : 'QUANDO'}</dt>
            <dd className="mail__address">{data.pending.when}</dd>
          </div>
          {data.pending.location && (
            <div>
              <dt>LOCAL</dt>
              <dd className="mail__address">{data.pending.location}</dd>
            </div>
          )}
          {data.code && <ConfirmCode action="Para gravar, diga “confirmar agenda” e o código" code={data.code} />}
        </dl>
      )}
      {data.status !== 'cancelled' &&
        (data.events.length === 0 ? (
          <div className="agd__empty">Nada marcado.</div>
        ) : (
          groups.map((group) => (
            <section key={group.day} className="agd__day" aria-label={group.day}>
              {severalDays && (
                <h3 className="agd__label">
                  {weekdayShort(group.day)} · {group.day.slice(8, 10)}/{group.day.slice(5, 7)}
                </h3>
              )}
              <ul className="agd__list">
                {group.events.map((event) => (
                  <EventRow key={`${event.id}-${event.start}`} event={event} highlight={event.id === data.highlight} now={now} />
                ))}
              </ul>
            </section>
          ))
        ))}
    </div>
  );
}
