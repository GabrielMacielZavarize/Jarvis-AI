import { useEffect, useRef } from 'react';
import type { StatusResult } from '../hooks/useServerStatus';
import { levels } from '../lib/audio';
import { BACKEND_LABELS, MODE_LABELS } from '../lib/catalog';
import type { JarvisMode } from '../lib/types';
import { Panel } from './Panel';

/** Voice level meter updated through a ref — no React renders per audio frame. */
function VoiceMeter({ channel, label }: { channel: 'agent' | 'user'; label: string }) {
  const fill = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      if (fill.current) fill.current.style.width = `${Math.min(100, levels[channel] * 140)}%`;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [channel]);

  return (
    <div className="stat meter">
      <dt>{label}</dt>
      <div className="meter__bar">
        <div className="meter__fill" ref={fill} style={{ width: 0 }} />
      </div>
    </div>
  );
}

interface SystemPanelProps {
  mode: JarvisMode;
  status: StatusResult;
  demo: boolean;
}

export function SystemPanel({ mode, status, demo }: SystemPanelProps) {
  const server = status.state === 'ok' ? status.status : null;
  const backend = server?.backend ? (BACKEND_LABELS[server.backend] ?? server.backend) : '—';

  return (
    <Panel code="SYS-00" title="Sistema" extra={<span>v{server?.version ?? '2.0.0'}</span>}>
      <dl className="stats">
        <div className="stat">
          <dt>Estado</dt>
          <dd>{MODE_LABELS[mode]}</dd>
        </div>
        <div className="stat">
          <dt>Núcleo</dt>
          <dd>{demo ? 'Simulação' : backend}</dd>
        </div>
        <div className="stat" style={{ gridColumn: '1 / -1' }}>
          <dt>Modelo</dt>
          <dd title={server?.model}>{demo ? 'jarvis-demo' : (server?.model ?? '—')}</dd>
        </div>
        <VoiceMeter channel="agent" label="Saída de voz · Jarvis" />
        <VoiceMeter channel="user" label="Entrada de voz · Você" />
      </dl>

      {status.state === 'unreachable' && !demo && (
        <div className="notice">
          <strong>Servidor offline.</strong> Rode <code>python jarvis.py</code> (ou <code>python server.py</code>) para
          habilitar a conexão. O modo simulação funciona mesmo assim.
        </div>
      )}
      {server && !server.ready && !demo && (
        <div className="notice">
          <strong>Configuração pendente.</strong>
          {server.errors.slice(0, 3).map((error) => (
            <div key={error}>· {error}</div>
          ))}
        </div>
      )}
    </Panel>
  );
}
