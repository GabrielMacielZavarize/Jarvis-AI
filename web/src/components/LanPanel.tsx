import { useCallback, useEffect, useState } from 'react';
import {
  cancelPairing,
  fetchLanInfo,
  formatCode,
  formatCountdown,
  formatSeen,
  type LanInfo,
  newPairingCode,
  revokeDevice,
} from '../lib/lan';
import { Panel } from './Panel';

/** While a code is shown, look for the phone that used it this often. */
const POLL_MS = 2000;

/** LAN-26, on the PC only: pairing code + QR for the phone and the list of paired devices. */
export function LanPanel() {
  const [info, setInfo] = useState<LanInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState(0);

  const run = useCallback(async (action: () => Promise<LanInfo>) => {
    try {
      const next = await action();
      setInfo(next);
      setLeft(next.expires_in);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Falha ao falar com o servidor.');
    }
  }, []);

  useEffect(() => {
    void run(fetchLanInfo);
  }, [run]);

  const code = info?.code ?? null;
  useEffect(() => {
    if (!code) return;
    const poll = window.setInterval(() => void run(fetchLanInfo), POLL_MS);
    const tick = window.setInterval(() => setLeft((value) => Math.max(0, value - 1)), 1000);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, [code, run]);

  if (!info?.enabled) return null;
  const devices = info.devices;

  return (
    <Panel code="LAN-26" title="Celular" className="lan" extra={<span>{devices.length} pareado(s)</span>}>
      <p className="lan__url">
        No celular: <strong>{info.urls[0]}</strong>
      </p>
      {code ? (
        <div className="lan__pairing">
          <img className="lan__qr" src={`/api/lan/qr.svg?c=${code}`} alt="QR para parear o celular" width={132} height={132} />
          <div className="lan__code-box">
            <span className="lan__code">{formatCode(code)}</span>
            <span className="lan__left">expira em {formatCountdown(left)}</span>
            <button type="button" className="btn btn--ghost" onClick={() => void run(cancelPairing)}>
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        <button type="button" className="btn btn--primary lan__start" onClick={() => void run(newPairingCode)}>
          Parear celular
        </button>
      )}
      {error && (
        <p className="lan__error" role="alert">
          {error}
        </p>
      )}
      {devices.length > 0 && (
        <ul className="lan__devices">
          {devices.map((device) => (
            <li key={device.id}>
              <span className="lan__device-name">{device.name}</span>
              <span className="lan__device-seen">{formatSeen(device.last_seen)}</span>
              <button
                type="button"
                className="btn btn--ghost lan__revoke"
                onClick={() => {
                  if (window.confirm(`Revogar ${device.name}? Ele perde o acesso na hora.`)) void run(() => revokeDevice(device.id));
                }}
              >
                Revogar
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
