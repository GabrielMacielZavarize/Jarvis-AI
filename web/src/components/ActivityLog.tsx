import { useHud } from '../lib/hudStore';
import { formatClock } from '../lib/format';
import type { LogLevel } from '../lib/types';
import { Panel } from './Panel';

const MARKS: Record<LogLevel, string> = {
  info: '·',
  tool: '◆',
  ok: '✓',
  warn: '!',
  error: '✕',
};

export function ActivityLog() {
  const log = useHud((s) => s.log);

  return (
    <Panel code="LOG-04" title="Registro" className="log" bodyClassName="panel__body--scroll" extra={<span>{log.length}</span>}>
      <ul className="log__list" aria-live="polite">
        {log.map((entry) => (
          <li key={entry.id} className={`log__item log__item--${entry.level}`}>
            <span className="log__time">{formatClock(entry.ts)}</span>
            <span className="log__mark" aria-hidden>
              {MARKS[entry.level]}
            </span>
            <span>{entry.text}</span>
          </li>
        ))}
        {log.length === 0 && <li className="log__empty">Sem eventos ainda.</li>}
      </ul>
    </Panel>
  );
}
