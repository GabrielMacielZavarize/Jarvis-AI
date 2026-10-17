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

export function TopBar({ mode, status, connected, micEnabled, demo, sessionStart }: TopBarProps) {
  const now = useClock(1000);
  const time = new Date(now);
  const linkLed = mode === 'error' ? 'led--off' : connected ? (mode === 'connecting' ? 'led--busy' : 'led--on') : '';

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand__mark" aria-hidden>
          <span />
          <span />
          <span />
        </div>
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
        <div className="clock__time">{time.toLocaleTimeString('pt-BR')}</div>
        <div className="clock__date">{dateFormatter.format(time).replace(/\./g, '').toUpperCase()}</div>
      </div>
    </header>
  );
}
