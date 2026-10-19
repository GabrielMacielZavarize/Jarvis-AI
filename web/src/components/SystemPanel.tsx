import { useEffect, useRef, useState } from 'react';
import { useClock } from '../hooks/useClock';
import type { StatusResult } from '../hooks/useServerStatus';
import { levels, SIGNAL_FLOOR } from '../lib/audio';
import { type PresenceState, presenceLabel } from '../lib/presence';
import { BACKEND_LABELS, MODE_LABELS } from '../lib/catalog';
import { useHud } from '../lib/hudStore';
import { formatSeconds, latencyTone } from '../lib/latency';
import type { JarvisMode } from '../lib/types';
import type { WakeWord } from '../hooks/useWakeWord';
import { Panel } from './Panel';
import { HudSettings } from './HudSettings';
import { SoundControls } from './SoundControls';

const SETTINGS_STORAGE_KEY = 'jarvis.hud.settings';

function loadSettingsOpen(): boolean {
  try {
    return window.localStorage.getItem(SETTINGS_STORAGE_KEY) === 'open';
  } catch {
    return false;
  }
}

/** Microphone and interface sounds stay folded behind "Ajustes"; the choice is kept in this browser. */
function useSettingsOpen() {
  const [open, setOpen] = useState(loadSettingsOpen);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    try {
      window.localStorage.setItem(SETTINGS_STORAGE_KEY, next ? 'open' : 'closed');
    } catch {
      // Private windows may refuse storage; the panel still toggles.
    }
  };
  return [open, toggle] as const;
}

function GearIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" />
    </svg>
  );
}

/** Voice level meter updated through a ref — no React renders per audio frame. */
function VoiceMeter({ channel, label, title }: { channel: 'agent' | 'user'; label: string; title: string }) {
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
    <div className={`stat meter meter--${channel}`}>
      <dt title={title}>{label}</dt>
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
  /** PRS-25, when JARVIS_PRESENCE=true. */
  presence?: PresenceState | null;
}

function wakeLabel(wake: WakeWord, connected: boolean): { text: string; ok: boolean } {
  if (!wake.detector) return { text: 'Detector offline · veja o terminal', ok: false };
  if (wake.listening && wake.micSilent) return { text: 'Sem sinal no microfone · mudo no Windows?', ok: false };
  if (wake.listening) return { text: 'Aguardando “Jarvis”', ok: true };
  return { text: connected ? 'Pausada durante o link' : 'Retomando escuta…', ok: false };
}

export function SystemPanel({ mode, status, demo, connected, micEnabled, microphone, wake, presence }: SystemPanelProps) {
  const server = status.state === 'ok' ? status.status : null;
  const backend = server?.backend ? (BACKEND_LABELS[server.backend] ?? server.backend) : '—';
  const live = connected && !demo;
  const silent = useSilentMicrophone(live && micEnabled);
  const heardAt = useHud((s) => s.userHeardAt);
  const liveModel = useHud((s) => s.liveModel);
  const latency = useHud((s) => s.latency);
  const model = live && liveModel ? liveModel : server?.model;
  const fallback = Boolean(live && liveModel && server?.model && liveModel !== server.model);
  const now = useClock(1000);
  const heardRecently = heardAt !== null && now - heardAt < 4000;
  const inputs = microphone.devices.filter((device) => device.deviceId);
  const [settingsOpen, toggleSettings] = useSettingsOpen();
  const micAlert = live && micEnabled && silent;
  // A silent microphone opens the settings: the warning points at the selector.
  const showSettings = settingsOpen || micAlert;

  return (
    <Panel
      code="SYS-00"
      title="Sistema"
      extra={
        <>
          <span>v{server?.version ?? '2.0.0'}</span>
          <button
            type="button"
            className={`chip-btn settings-btn ${showSettings ? 'settings-btn--open' : ''}`}
            onClick={toggleSettings}
            aria-expanded={showSettings}
            title="Microfone e sons da interface"
          >
            <GearIcon /> Ajustes
          </button>
        </>
      }
    >
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
          <dt>Modelo{fallback ? ' · reserva' : ''}</dt>
          <dd title={fallback ? `Reserva no lugar de ${server?.model}` : model}>{demo ? 'jarvis-demo' : (model ?? '—')}</dd>
        </div>
        {latency && !demo && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt title="Do fim da sua fala até a primeira palavra do Jarvis">Tempo de resposta</dt>
            <dd className={`latency latency--${latencyTone(latency.last)}`}>
              {formatSeconds(latency.last)}
              <small>média {formatSeconds(latency.average)} · {latency.samples.length} turnos</small>
            </dd>
          </div>
        )}
        {server?.voice && !demo && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>Voz · VOZ-30</dt>
            <dd title="JARVIS_VOICE ou “Jarvis, troca sua voz para…”">{server.voice}</dd>
          </div>
        )}
        <VoiceMeter channel="agent" label="Jarvis" title="Saída de voz · Jarvis" />
        <VoiceMeter channel="user" label="Você" title="Entrada de voz · Você" />
        {showSettings && !demo && inputs.length > 0 && (
          <div className="stat stat--setting" style={{ gridColumn: '1 / -1' }}>
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
        {showSettings && <SoundControls />}
        {showSettings && <HudSettings />}
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
        {presence && !demo && (
          <div className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>Presença · PRS-25</dt>
            <dd className={presenceLabel(presence, now).ok ? 'ok-text' : undefined}>{presenceLabel(presence, now).text}</dd>
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

      {micAlert && (
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
