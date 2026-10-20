import { PROTOCOLS } from '../lib/catalog';
import { Panel } from './Panel';

/** `hints` replaces the example line of a protocol that is on (MCP-32 lists its servers). */
export function ProtocolsPanel({ enabled, hints = {} }: { enabled: string[] | null; hints?: Record<string, string | null> }) {
  return (
    <Panel code="PRT-01" title="Protocolos" extra={<span>{PROTOCOLS.length} módulos</span>} className="card">
      <ul className="protocols">
        {PROTOCOLS.map((protocol) => {
          const on = enabled === null || enabled.includes(protocol.id);
          return (
            <li key={protocol.id} className={`protocol ${on ? '' : 'protocol--off'}`}>
              <span className="protocol__code">{protocol.code}</span>
              <span className="protocol__label">
                {protocol.label}
                <span className="protocol__hint">{on ? (hints[protocol.id] ?? protocol.hint) : 'Desativado no .env'}</span>
              </span>
              <i className={`led ${on ? 'led--on' : ''}`} />
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
