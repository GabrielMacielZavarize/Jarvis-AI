import { useClock } from '../hooks/useClock';
import { BACKEND_LABELS } from '../lib/catalog';
import { formatDuration } from '../lib/format';
import { usePrefs } from '../lib/prefs';
import { type ThemeId, themeInfo } from '../lib/themes';
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
const COILS = Array.from({ length: 16 }, (_, index) => index * 22.5);

/**
 * The persona's emblem: J.A.R.V.I.S. the arc reactor with the Mark VI triangle, Mark III the round
 * reactor of the first armour (more cells, no triangle), F.R.I.D.A.Y. a gyroscope, Stealth a bare ring.
 */
export function PersonaMark({ theme, className = 'brand__mark' }: { theme: ThemeId; className?: string }) {
  if (theme === 'friday') {
    return (
      <svg className={className} viewBox="0 0 48 48" aria-hidden>
        <circle className="brand__ring" cx="24" cy="24" r="22" />
        <g className="brand__cells brand__cells--orbits">
          <ellipse cx="24" cy="24" rx="17" ry="6.5" />
          <ellipse cx="24" cy="24" rx="17" ry="6.5" transform="rotate(60 24 24)" />
          <ellipse cx="24" cy="24" rx="17" ry="6.5" transform="rotate(120 24 24)" />
        </g>
        <circle className="brand__core" cx="24" cy="24" r="4.2" />
      </svg>
    );
  }
  if (theme === 'stealth') {
    return (
      <svg className={className} viewBox="0 0 48 48" aria-hidden>
        <circle className="brand__ring" cx="24" cy="24" r="22" />
        <circle className="brand__inner" cx="24" cy="24" r="12.5" />
        <circle className="brand__core" cx="24" cy="24" r="2.6" />
      </svg>
    );
  }
  const mark3 = theme === 'mark3';
  return (
    <svg className={className} viewBox="0 0 48 48" aria-hidden>
      <circle className="brand__ring" cx="24" cy="24" r="22" />
      <g className="brand__cells">
        {(mark3 ? COILS : SEGMENTS).map((angle) => (
          <rect
            key={angle}
            x={mark3 ? 22.9 : 22.4}
            y="5.2"
            width={mark3 ? 2.2 : 3.2}
            height={mark3 ? 8 : 6}
            rx="0.8"
            transform={`rotate(${angle} 24 24)`}
          />
        ))}
      </g>
      <circle className="brand__inner" cx="24" cy="24" r="12.5" />
      {!mark3 && <path className="brand__tri" d="M24 15.5 31.4 28.3H16.6Z" />}
      <circle className="brand__core" cx="24" cy="24" r={mark3 ? 5.4 : 3.6} />
    </svg>
  );
}

export function TopBar({ mode, status, connected, micEnabled, demo, sessionStart }: TopBarProps) {
  const now = useClock(1000);
  const time = new Date(now);
  const [hours, minutes, seconds] = time.toLocaleTimeString('pt-BR').split(':');
  const linkLed = mode === 'error' ? 'led--off' : connected ? (mode === 'connecting' ? 'led--busy' : 'led--on') : '';
  const { theme } = usePrefs();
  const persona = themeInfo(theme);

  return (
    <header className="topbar">
      <div className="brand">
        <PersonaMark theme={theme} />
        <div>
          <h1 className="brand__name">{persona.brand}</h1>
          <div className="brand__tag">{persona.tagline}</div>
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
