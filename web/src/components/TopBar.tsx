import { useClock } from '../hooks/useClock';
import { BACKEND_LABELS } from '../lib/catalog';
import { formatDuration } from '../lib/format';
import type { JarvisMode, ServerStatus } from '../lib/types';

interface TopBarProps {
  mode: JarvisMode;
  status: ServerStatus | null;
  connected: boolean;
  micEnabled: boolean;
  demo: boolean;
  sessionStart: number | null;
}

const dateFormatter = new Intl.DateTimeFormat('pt-BR', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
const SEGMENTS = Array.from({ length: 10 }, (_, index) => index * 36);

/** Arc reactor: a ring of turning cells around the triangle of the Mark VI. */
function ReactorMark() {
  return (
    <svg className="brand__mark" viewBox="0 0 48 48" aria-hidden>
      <circle className="brand__ring" cx="24" cy="24" r="22" />
      <g className="brand__cells">
        {SEGMENTS.map((angle) => (
          <rect key={angle} x="22.4" y="5.2" width="3.2" height="6" rx="0.8" transform={`rotate(${angle} 24 24)`} />
        ))}
      </g>
      <circle className="brand__inner" cx="24" cy="24" r="12.5" />
      <path className="brand__tri" d="M24 15.5 31.4 28.3H16.6Z" />
      <circle className="brand__core" cx="24" cy="24" r="3.6" />
    </svg>
  );
}

export function TopBar({ mode, status, connected, micEnabled, demo, sessionStart }: TopBarProps) {
  const now = useClock(1000);
  const time = new Date(now);
  const [hours, minutes, seconds] = time.toLocaleTimeString('pt-BR').split(':');
  const linkLed = mode === 'error' ? 'led--off' : connected ? (mode === 'connecting' ? 'led--busy' : 'led--on') : '';

  return (
    <header className="topbar">
      <div className="brand">
        <ReactorMark />
        <div>
          <h1 className="brand__name">J.A.R.V.I.S.</h1>
          <div className="brand__tag">Just A Rather Very Intelligent System</div>
        </div>
      </div>

      <div className="chips">
        {demo && <div className="chip chip--demo">Simulação</div>}
        <div className="chip">
          <i className={`led ${linkLed}`} /> Link <b>{connected ? (mode === 'connecting' ? 'sincronizando' : 'ativo') : 'inativo'}</b>
        </div>
        <div className="chip">
          Núcleo <b>{demo ? 'Simulado' : status?.backend ? (BACKEND_LABELS[status.backend] ?? status.backend) : '—'}</b>
        </div>
        <div className="chip">
          <i className={`led ${demo ? 'led--on' : connected ? (micEnabled ? 'led--on' : 'led--off') : ''}`} /> Mic{' '}
          <b>{demo ? 'simulado' : connected ? (micEnabled ? 'aberto' : 'mudo') : '—'}</b>
        </div>
        <div className="chip">
          Sessão <b>{sessionStart ? formatDuration((now - sessionStart) / 1000) : '00:00'}</b>
        </div>
      </div>

      <div className="clock">
        <div className="clock__time">
          {hours}
          <span className="clock__sep">:</span>
          {minutes}
          <small>{seconds}</small>
        </div>
        <div className="clock__date">{dateFormatter.format(time).replace(/\./g, '').toUpperCase()}</div>
        <div className="clock__seconds" aria-hidden>
          <i style={{ width: `${(Number(seconds) / 59) * 100}%` }} />
        </div>
      </div>
    </header>
  );
}
