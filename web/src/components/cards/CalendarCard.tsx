import { useClock } from '../../hooks/useClock';
import { CALENDAR_ACTIONS, CALENDAR_STATUS, eventTime, groupByDay, isOngoing } from '../../lib/calendar';
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
