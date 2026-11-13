import type { ChatLine, JarvisMode } from '../lib/types';

// O estado do link com o Jarvis, separado do hook que o preenche: o hook puxa o LiveKit inteiro,
// e a abertura do HUD só precisa deste formato (e do OFFLINE_LIVE) para pintar a tela.

export interface LiveJarvis {
  mode: JarvisMode;
  connected: boolean;
  lines: ChatLine[];
  micEnabled: boolean;
  micDevices: MediaDeviceInfo[];
  micDeviceId: string;
  selectMic: (deviceId: string) => Promise<void>;
  error: string | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  toggleMic: () => Promise<void>;
  send: (text: string) => Promise<void>;
}

const noop = async () => {};

/** Used while LiveKit is not configured: no session, no token requests. */
export const OFFLINE_LIVE: LiveJarvis = {
  mode: 'standby',
  connected: false,
  lines: [],
  micEnabled: false,
  micDevices: [],
  micDeviceId: 'default',
  selectMic: noop,
  error: null,
  start: noop,
  stop: noop,
  toggleMic: noop,
  send: noop,
};
