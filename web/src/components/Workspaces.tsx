import type { ReactNode } from 'react';
import type { StatusResult } from '../hooks/useServerStatus';
import type { WakeWord } from '../hooks/useWakeWord';
import { mcpHint } from '../lib/catalog';
import type { PresenceState } from '../lib/presence';
import type { JarvisMode } from '../lib/types';
import { viewInfo, type ViewId } from '../lib/views';
import { GesturesPanel } from './GesturesPanel';
import { HealthPanel } from './HealthPanel';
import { HudSettings } from './HudSettings';
import { LanPanel } from './LanPanel';
import { Panel } from './Panel';
import { ProtocolsPanel } from './ProtocolsPanel';
import { SoundControls } from './SoundControls';
import { type MicrophoneProps, SystemPanel, VoiceMeter } from './SystemPanel';

/** Moldura das áreas que abrem por cima do núcleo: título, o que ela mostra e os painéis em colunas. */
export function Workspace({ view, children }: { view: ViewId; children: ReactNode }) {
  const info = viewInfo(view);
  return (
    <section className="workspace" aria-label={info.label} data-view={view}>
      <header className="workspace__head">
        <h2>{info.label}</h2>
        <p>{info.hint}</p>
      </header>
      <div className="workspace__grid">{children}</div>
    </section>
  );
}

interface SystemViewProps {
  mode: JarvisMode;
  status: StatusResult;
  demo: boolean;
  connected: boolean;
  micEnabled: boolean;
  wake: WakeWord | null;
  presence: PresenceState | null;
  /** O HUD está no próprio PC (o painel Celular não aparece dentro do celular). */
  local: boolean;
}

/** Sistema: como o link e o agente estão, o que o Jarvis sabe fazer, saúde, gestos e celular. */
export function SystemView({ mode, status, demo, connected, micEnabled, wake, presence, local }: SystemViewProps) {
  const server = status.state === 'ok' ? status.status : null;
  return (
    <Workspace view="system">
      <div className="workspace__col">
        <SystemPanel mode={mode} status={status} demo={demo} connected={connected} micEnabled={micEnabled} wake={wake} presence={presence} />
        {server && <HealthPanel local={local} />}
        {local && server?.lan && <LanPanel />}
      </div>
      {server?.gestures && (
        <div className="workspace__col">
          <GesturesPanel connected={connected && !demo} />
        </div>
      )}
      <div className="workspace__col workspace__col--wide">
        <ProtocolsPanel enabled={server?.tools ?? null} hints={{ mcp_status: mcpHint(server?.mcp) }} />
      </div>
    </Workspace>
  );
}

const SHORTCUTS: { keys: string[]; what: string }[] = [
  { keys: ['Espaço'], what: 'Inicia o link (ou diga “Jarvis”)' },
  { keys: ['Ctrl', 'K'], what: 'Paleta de comandos' },
  { keys: ['1', '2', '3', '4', '5'], what: 'Painel, Dia a dia, Olho de Deus, Sistema e Ajustes' },
  { keys: ['M'], what: 'Silencia ou ativa o microfone' },
  { keys: ['/'], what: 'Vai para a linha de comando de texto' },
  { keys: ['F'], what: 'Modo cinema' },
  { keys: ['Esc'], what: 'Fecha o painel ampliado, o cinema e depois as projeções' },
];

/** Ajustes: aparência do HUD, áudio e os atalhos de teclado. Tudo fica salvo neste navegador. */
export function SettingsView({ microphone, demo }: { microphone: MicrophoneProps; demo: boolean }) {
  const inputs = microphone.devices.filter((device) => device.deviceId);
  return (
    <Workspace view="settings">
      <Panel code="SET-01" title="Aparência">
        <dl className="stats">
          <HudSettings />
        </dl>
      </Panel>
      <Panel code="SET-02" title="Áudio">
        <dl className="stats">
          <div className="stat stat--setting" style={{ gridColumn: '1 / -1' }}>
            <dt>
              <label htmlFor="mic-select">Microfone</label>
            </dt>
            <dd>
              {!demo && inputs.length > 0 ? (
                <select id="mic-select" className="select" value={microphone.deviceId} onChange={(event) => microphone.onSelect(event.target.value)}>
                  {inputs.map((device, index) => (
                    <option key={device.deviceId} value={device.deviceId}>
                      {device.label || `Microfone ${index + 1}`}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="stat__empty">A lista aparece com o link aberto, depois que o navegador libera o microfone.</span>
              )}
            </dd>
          </div>
          <VoiceMeter channel="user" label="Você" title="Entrada de voz · Você" />
          <VoiceMeter channel="agent" label="Jarvis" title="Saída de voz · Jarvis" />
          <SoundControls />
        </dl>
      </Panel>
      <Panel code="SET-03" title="Atalhos">
        <ul className="shortcuts">
          {SHORTCUTS.map((shortcut) => (
            <li key={shortcut.what}>
              <span className="shortcuts__keys">
                {shortcut.keys.map((key) => (
                  <kbd key={key}>{key}</kbd>
                ))}
              </span>
              <span>{shortcut.what}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </Workspace>
  );
}
