import { HudSettings } from './HudSettings';
import { Panel } from './Panel';
import { SoundControls } from './SoundControls';
import { type MicrophoneProps, VoiceMeter } from './SystemPanel';
import { Workspace } from './Workspace';

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
