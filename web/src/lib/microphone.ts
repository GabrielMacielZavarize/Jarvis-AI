import type { MicReport } from './types';

interface MicSnapshot {
  /** Label of the track being captured right now (the most reliable name). */
  trackLabel?: string | null;
  deviceId: string;
  devices: Pick<MediaDeviceInfo, 'deviceId' | 'label'>[];
  enabled: boolean;
  signalAt: number | null;
  heardAt: number | null;
  now: number;
}

const VIRTUAL_IDS = new Set(['default', 'communications']);

const secondsSince = (ts: number | null, now: number) => (ts === null ? null : Math.max(0, Math.round((now - ts) / 1000)));

/** What the agent hears about the microphone selected in the Sistema panel. */
export function describeMicrophone(snapshot: MicSnapshot): MicReport {
  const { deviceId, devices, now } = snapshot;
  const chosen = devices.find((device) => device.deviceId === deviceId);
  // "default"/"communications" are the browser's aliases of a real device listed anyway.
  const real = devices.filter((device) => !VIRTUAL_IDS.has(device.deviceId));
  const available = [...new Set(real.map((device) => device.label).filter(Boolean))].slice(0, 8);
  return {
    label: snapshot.trackLabel || chosen?.label || null,
    device_id: deviceId,
    is_default: deviceId === 'default',
    enabled: snapshot.enabled,
    signal_s: secondsSince(snapshot.signalAt, now),
    heard_s: secondsSince(snapshot.heardAt, now),
    available,
  };
}
