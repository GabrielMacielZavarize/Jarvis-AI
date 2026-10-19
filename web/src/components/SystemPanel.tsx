import { useEffect, useRef, useState } from 'react';
import { useClock } from '../hooks/useClock';
import type { StatusResult } from '../hooks/useServerStatus';
import { levels, SIGNAL_FLOOR } from '../lib/audio';
import { BACKEND_LABELS, MODE_LABELS } from '../lib/catalog';
import { useHud } from '../lib/hudStore';
import type { JarvisMode } from '../lib/types';
import type { WakeWord } from '../hooks/useWakeWord';
import { Panel } from './Panel';
import { SoundControls } from './SoundControls';

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

/** True when the open microphone delivered no signal at all for a few seconds. */
function useSilentMicrophone(active: boolean) {
  const [silent, setSilent] = useState(false);
  useEffect(() => {
    if (!active) {
      setSilent(false);
      return;
    }
    let frame = 0;
    let peak = 0;
    let windowStart = performance.now();
    const tick = (now: number) => {
      peak = Math.max(peak, levels.user);
      if (now - windowStart > 6000) {
        setSilent(peak < SIGNAL_FLOOR);
        peak = 0;
        windowStart = now;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active]);
  return silent;
}

interface MicrophoneProps {
  devices: MediaDeviceInfo[];
  deviceId: string;
  onSelect: (deviceId: string) => void;
}

interface SystemPanelProps {
  mode: JarvisMode;
  status: StatusResult;
  demo: boolean;
  connected: boolean;
  micEnabled: boolean;
  microphone: MicrophoneProps;
  /** WAK-22, when JARVIS_WAKE_WORD=true. */
  wake?: WakeWord | null;
}

function wakeLabel(wake: WakeWord, connected: boolean): { text: string; ok: boolean } {
  if (!wake.detector) return { text: 'Detector offline · veja o terminal', ok: false };
  if (wake.listening && wake.micSilent) return { text: 'Sem sinal no microfone · mudo no Windows?', ok: false };
  if (wake.listening) return { text: 'Aguardando “Jarvis”', ok: true };
  return { text: connected ? 'Pausada durante o link' : 'Retomando escuta…', ok: false };
}

export function SystemPanel({ mode, status, demo, connected, micEnabled, microphone, wake }: SystemPanelProps) {
  const server = status.state === 'ok' ? status.status : null;
  const backend = server?.backend ? (BACKEND_LABELS[server.backend] ?? server.backend) : '—';
  const live = connected && !demo;
  const silent = useSilentMicrophone(live && micEnabled);
  const heardAt = useHud((s) => s.userHeardAt);
  const now = useClock(1000);
  const heardRecently = heardAt !== null && now - heardAt < 4000;
  const inputs = microphone.devices.filter((device) => device.deviceId);

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
        {server?.voice && !demo && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>Voz · VOZ-30</dt>
            <dd title="JARVIS_VOICE ou “Jarvis, troca sua voz para…”">{server.voice}</dd>
          </div>
        )}
        <VoiceMeter channel="agent" label="Saída de voz · Jarvis" />
        <VoiceMeter channel="user" label="Entrada de voz · Você" />
        {!demo && inputs.length > 0 && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>
              <label htmlFor="mic-select">Microfone</label>
            </dt>
            <dd>
              <select
                id="mic-select"
                className="select"
                value={microphone.deviceId}
                onChange={(event) => microphone.onSelect(event.target.value)}
              >
                {inputs.map((device, index) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || `Microfone ${index + 1}`}
                  </option>
                ))}
              </select>
            </dd>
          </div>
        )}
        <SoundControls />
        {wake && !demo && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>Ativação por voz · WAK-22</dt>
            <dd className={wakeLabel(wake, connected).ok ? 'ok-text' : undefined}>{wakeLabel(wake, connected).text}</dd>
          </div>
        )}
        {server?.proactive && !demo && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>Avisos proativos · PRO-28</dt>
            <dd className="ok-text">Lembretes, bateria, CPU/RAM, downloads e disco</dd>
          </div>
        )}
        {live && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>Captação no agente</dt>
            <dd className={heardRecently ? 'ok-text' : undefined}>
              {heardRecently ? 'Ouvindo sua voz agora' : heardAt ? 'Voz já detectada nesta sessão' : 'Nenhuma fala detectada ainda'}
            </dd>
          </div>
        )}
      </dl>

      {live && micEnabled && silent && (
        <div className="notice" role="alert">
          <strong>Sem sinal do microfone.</strong> O navegador não está recebendo áudio. Escolha o microfone do seu fone
          acima ou confira se ele não está mudo no Windows.
        </div>
      )}

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
