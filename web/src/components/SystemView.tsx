import type { StatusResult } from '../hooks/useServerStatus';
import type { WakeWord } from '../hooks/useWakeWord';
import { mcpHint } from '../lib/catalog';
import type { PresenceState } from '../lib/presence';
import type { JarvisMode } from '../lib/types';
import { GesturesPanel } from './GesturesPanel';
import { HealthPanel } from './HealthPanel';
import { LanPanel } from './LanPanel';
import { ProtocolsPanel } from './ProtocolsPanel';
import { SystemPanel } from './SystemPanel';
import { Workspace } from './Workspace';

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
