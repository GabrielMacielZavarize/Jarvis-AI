import { useAgent, useLocalParticipant, useSessionContext, useSessionMessages } from '@livekit/components-react';
import type { ReceivedMessage } from '@livekit/components-core';
import {
  ConnectionState,
  type LocalAudioTrack,
  type RemoteAudioTrack,
  type Room,
  RoomEvent,
  Track,
} from 'livekit-client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { attachTrack, lastUserSignalAt } from '../lib/audio';
import { TOOL_LABELS } from '../lib/catalog';
import { useHud } from '../lib/hudStore';
import { describeMicrophone } from '../lib/microphone';
import { parseHudRequest } from '../lib/panels';
import { orderLines } from '../lib/transcript';
import type { ChatLine, HudEvent, JarvisMode, MicReport } from '../lib/types';

export const HUD_TOPIC = 'jarvis.hud';
const HUD_RPC_METHOD = 'jarvis.hud';
const SCREEN_TOPIC = 'jarvis.screen';
let lastScreenUrl: string | null = null;

const decoder = new TextDecoder();
const MIC_STORAGE_KEY = 'jarvis.microphone';
// Lets the RPC reply reach the agent before the room goes away.
const END_LINK_DELAY_MS = 250;

function loadSavedMic(): string | null {
  try {
    return window.localStorage.getItem(MIC_STORAGE_KEY);
  } catch {
    return null;
  }
}

function saveMic(deviceId: string) {
  try {
    window.localStorage.setItem(MIC_STORAGE_KEY, deviceId);
  } catch {
    // Storage blocked: the choice simply won't survive a reload.
  }
}

function toLine(message: ReceivedMessage): ChatLine | null {
  const text = 'message' in message ? message.message : '';
  if (!text?.trim()) return null;
  let role: ChatLine['role'];
  if (message.type === 'userTranscript') role = 'user';
  else if (message.type === 'agentTranscript') role = 'agent';
  else role = message.from?.isLocal ? 'user' : 'agent';
  return { id: message.id, role, text, ts: message.timestamp, spoken: message.type === 'userTranscript' };
}

/** Audio inputs, re-read whenever `refreshKey` changes (e.g. right after mic permission is granted). */
function useAudioInputs(refreshKey: unknown) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  useEffect(() => {
    const media = navigator.mediaDevices;
    if (!media?.enumerateDevices) return;
    let cancelled = false;
    const load = () => {
      media
        .enumerateDevices()
        .then((all) => {
          if (!cancelled) setDevices(all.filter((device) => device.kind === 'audioinput' && device.deviceId));
        })
        .catch(() => undefined);
    };
    load();
    media.addEventListener('devicechange', load);
    return () => {
      cancelled = true;
      media.removeEventListener('devicechange', load);
    };
  }, [refreshKey]);
  return devices;
}

/** The microphone this browser is really capturing from, for "qual microfone está conectado?". */
async function microphoneReport(room: Room): Promise<MicReport> {
  const track = room.localParticipant.getTrackPublication(Track.Source.Microphone)?.track?.mediaStreamTrack;
  let devices: MediaDeviceInfo[] = [];
  try {
    devices = (await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === 'audioinput');
  } catch {
    // Without device access the track label is still reported.
  }
  return describeMicrophone({
    trackLabel: track?.label,
    deviceId: room.getActiveDevice('audioinput') || loadSavedMic() || 'default',
    devices,
    enabled: room.localParticipant.isMicrophoneEnabled,
    signalAt: lastUserSignalAt(),
    heardAt: useHud.getState().userHeardAt,
    now: Date.now(),
  });
}

function handleHudEvent(event: HudEvent) {
  const hud = useHud.getState();
  if (event.type === 'tool') {
    const label = TOOL_LABELS[event.name] ?? event.name;
    const detail = event.detail ? ` · ${event.detail}` : '';
    if (event.status === 'running') {
      hud.setActiveTool(event.name);
      hud.addLog('tool', `${label}${detail}`);
    } else {
      if (hud.activeTool === event.name) hud.setActiveTool(null);
      hud.addLog(event.status === 'done' ? 'ok' : 'error', `${label} ${event.status === 'done' ? 'concluído' : 'falhou'}${detail}`);
    }
    return;
  }
  if (event.type === 'voice') {
    if (hud.userHeardAt === null) hud.addLog('ok', 'Jarvis está captando sua voz');
    hud.setUserHeardAt(Date.now());
    hud.addVoiceStart(Date.now());
    return;
  }
  if (event.type === 'net') {
    hud.addLinks(event.hosts, event.kind);
    if (event.kind === 'source') hud.addLog('info', `Fontes: ${event.hosts.slice(0, 4).join(', ')}`);
    return;
  }
  if (event.type === 'hud') {
    if (event.action === 'clear') {
      hud.clearCards();
      hud.addLog('info', 'Painéis do HUD limpos');
    } else {
      hud.closeCards(event.kinds);
      hud.addLog('info', `Painéis fechados: ${event.kinds.join(', ')}`);
    }
    return;
  }
  if (event.type === 'card') {
    if (event.kind === 'timer' && event.data.status === 'done') {
      const existing = hud.cards.find((card) => card.kind === 'timer' && card.data.id === event.data.id);
      hud.pushCard('timer', { ...(existing?.data as typeof event.data), ...event.data });
      hud.addLog('warn', `Timer “${event.data.label}” finalizado`);
      return;
    }
    hud.pushCard(event.kind, event.data as never);
  }
}

function describeStartError(err: unknown): string {
  const name = err instanceof Error ? err.name : '';
  const message = err instanceof Error ? err.message : String(err);
  if (name === 'NotAllowedError' || /permission denied|not allowed/i.test(message)) {
    return 'Permissão de microfone negada. Libere o microfone para este site e tente de novo.';
  }
  if (name === 'NotFoundError' || /requested device not found/i.test(message)) {
    return 'Nenhum microfone encontrado. Conecte um microfone e tente de novo.';
  }
  if (/503|LIVEKIT_/.test(message)) {
    return 'LiveKit não configurado. Preencha LIVEKIT_URL, LIVEKIT_API_KEY e LIVEKIT_API_SECRET no .env.';
  }
  if (/could not establish|websocket|signal connection|failed to fetch/i.test(message)) {
    return 'Não foi possível alcançar o servidor LiveKit. Confira LIVEKIT_URL e sua conexão.';
  }
  return `Falha ao conectar: ${message}`;
}

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

export function useLiveJarvis(): LiveJarvis {
  const session = useSessionContext();
  const agent = useAgent(session);
  const { messages, send: sendMessage } = useSessionMessages(session);
  const { isMicrophoneEnabled, localParticipant } = useLocalParticipant();
  const [error, setError] = useState<string | null>(null);
  const announced = useRef<string>('');

  const room = session.room;
  const connectionState = session.connectionState;
  const [savedMic, setSavedMic] = useState(loadSavedMic);
  // The RPC handler is registered once per room; it always calls the latest stop().
  const stopRef = useRef<() => Promise<void>>(async () => {});

  // HUD events published by the Python tools over the data channel.
  useEffect(() => {
    const onData = (payload: Uint8Array, _participant?: unknown, _kind?: unknown, topic?: string) => {
      if (topic !== HUD_TOPIC) return;
      try {
        handleHudEvent(JSON.parse(decoder.decode(payload)) as HudEvent);
      } catch (err) {
        console.warn('[jarvis] evento de HUD inválido', err);
      }
    };
    room.on(RoomEvent.DataReceived, onData);

    // The agent asks the HUD to list/close/expand panels, which microphone is in use, or to end
    // the link ("tchau, Jarvis"), and gets back what actually happened.
    room.registerRpcMethod(HUD_RPC_METHOD, async (data) => {
      const request = parseHudRequest(data.payload);
      const hud = useHud.getState();
      if (request.action === 'mic') return JSON.stringify({ mic: await microphoneReport(room) });
      if (request.action === 'end_session') {
        hud.addLog('info', 'Jarvis encerrou o link a seu pedido');
        window.setTimeout(() => void stopRef.current(), END_LINK_DELAY_MS);
        return JSON.stringify({ ended: true });
      }
      const result = hud.runPanelCommand(request.action, request.targets);
      if (result.changed.length > 0) {
        hud.addLog('info', `HUD: ${request.action} ${result.changed.map((panel) => panel.title).join(', ')}`);
      }
      return JSON.stringify(result);
    });

    // Screenshots Jarvis looked at, so the user sees exactly what was analysed.
    room.registerByteStreamHandler(SCREEN_TOPIC, async (reader) => {
      const chunks = await reader.readAll();
      const blob = new Blob(chunks as BlobPart[], { type: reader.info.mimeType || 'image/jpeg' });
      if (lastScreenUrl) URL.revokeObjectURL(lastScreenUrl);
      lastScreenUrl = URL.createObjectURL(blob);
      const label = reader.info.attributes?.label ?? 'tela';
      useHud.getState().pushCard('screen', { url: lastScreenUrl, label, takenAt: Date.now() });
      useHud.getState().addLog('info', `Print analisado · ${label}`);
    });

    return () => {
      room.off(RoomEvent.DataReceived, onData);
      room.unregisterRpcMethod(HUD_RPC_METHOD);
      room.unregisterByteStreamHandler(SCREEN_TOPIC);
    };
  }, [room]);

  // Feed both voices into the analyser that drives the 3D core.
  const agentTrack = agent.microphoneTrack?.publication?.track as RemoteAudioTrack | undefined;
  const userTrack = session.local.microphoneTrack?.publication?.track as LocalAudioTrack | undefined;
  useEffect(() => attachTrack('agent', agentTrack), [agentTrack]);
  useEffect(() => attachTrack('user', isMicrophoneEnabled ? userTrack : undefined), [userTrack, isMicrophoneEnabled]);

  const micDevices = useAudioInputs(userTrack);
  const micDeviceId = (userTrack && room.getActiveDevice('audioinput')) || savedMic || 'default';

  const mode: JarvisMode = useMemo(() => {
    if (agent.state === 'failed') return 'error';
    if (connectionState === ConnectionState.Disconnected) return 'standby';
    switch (agent.state) {
      case 'listening':
      case 'idle':
        return 'listening';
      case 'thinking':
        return 'thinking';
      case 'speaking':
        return 'speaking';
      default:
        return 'connecting';
    }
  }, [agent.state, connectionState]);

  // Connection milestones in the activity log.
  useEffect(() => {
    const hud = useHud.getState();
    const key = `${connectionState}:${agent.state === 'failed' ? 'failed' : agent.isConnected ? 'agent' : 'wait'}`;
    if (key === announced.current) return;
    announced.current = key;
    if (connectionState === ConnectionState.Connected && agent.isConnected) {
      hud.addLog('ok', 'J.A.R.V.I.S. online');
      hud.addLinks(['livekit.cloud'], 'link');
    }
    else if (connectionState === ConnectionState.Connected) hud.addLog('info', 'Link estabelecido · aguardando agente');
    else if (connectionState === ConnectionState.Reconnecting) hud.addLog('warn', 'Reconectando…');
    if (agent.state === 'failed') {
      const reasons = agent.failureReasons?.join(' ') || 'O agente não respondeu.';
      setError(`${reasons} Verifique se o worker está rodando (python agent.py dev).`);
      hud.addLog('error', 'Agente não respondeu');
    }
  }, [connectionState, agent.state, agent.isConnected, agent.failureReasons]);

  const voiceStarts = useHud((s) => s.voiceStarts);
  const arrival = useRef(new Map<string, number>());
  const lines = useMemo(
    () =>
      orderLines(
        messages.map(toLine).filter((line): line is ChatLine => line !== null),
        arrival.current,
        voiceStarts,
      ),
    [messages, voiceStarts],
  );

  const start = useCallback(async () => {
    setError(null);
    useHud.getState().resetVoice();
    useHud.getState().addLog('info', 'Solicitando credenciais de acesso…');
    // Capture from the microphone chosen in the HUD; "ideal" falls back to the default if it is gone.
    if (savedMic) room.options.audioCaptureDefaults = { ...room.options.audioCaptureDefaults, deviceId: { ideal: savedMic } };
    try {
      await session.start({ tracks: { microphone: { enabled: true } } });
    } catch (err) {
      setError(describeStartError(err));
      useHud.getState().addLog('error', 'Falha ao estabelecer link');
    }
  }, [session, room, savedMic]);

  const stop = useCallback(async () => {
    await session.end();
    attachTrack('agent', undefined);
    attachTrack('user', undefined);
    useHud.getState().setActiveTool(null);
    useHud.getState().addLog('info', 'Sessão encerrada');
  }, [session]);
  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);

  const toggleMic = useCallback(async () => {
    try {
      await localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled);
    } catch (err) {
      setError(`Microfone indisponível: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [localParticipant, isMicrophoneEnabled]);

  const selectMic = useCallback(
    async (deviceId: string) => {
      saveMic(deviceId);
      setSavedMic(deviceId);
      room.options.audioCaptureDefaults = { ...room.options.audioCaptureDefaults, deviceId: { ideal: deviceId } };
      const label = micDevices.find((device) => device.deviceId === deviceId)?.label || deviceId;
      try {
        if (connectionState !== ConnectionState.Disconnected) await room.switchActiveDevice('audioinput', deviceId);
        useHud.getState().addLog('info', `Microfone: ${label}`);
      } catch (err) {
        setError(`Não foi possível trocar o microfone: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
    [room, micDevices, connectionState],
  );

  const send = useCallback(
    async (text: string) => {
      await sendMessage(text);
    },
    [sendMessage],
  );

  const connected = connectionState !== ConnectionState.Disconnected;
  return useMemo(
    () => ({
      mode,
      connected,
      lines,
      micEnabled: isMicrophoneEnabled,
      micDevices,
      micDeviceId,
      selectMic,
      error,
      start,
      stop,
      toggleMic,
      send,
    }),
    [mode, connected, lines, isMicrophoneEnabled, micDevices, micDeviceId, selectMic, error, start, stop, toggleMic, send],
  );
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
