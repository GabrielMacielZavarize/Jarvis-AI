import { useAgent, useLocalParticipant, useSessionContext, useSessionMessages } from '@livekit/components-react';
import type { ReceivedMessage } from '@livekit/components-core';
import { ConnectionState, type LocalAudioTrack, type RemoteAudioTrack, RoomEvent } from 'livekit-client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { attachTrack } from '../lib/audio';
import { TOOL_LABELS } from '../lib/catalog';
import { useHud } from '../lib/hudStore';
import type { ChatLine, HudEvent, JarvisMode } from '../lib/types';

export const HUD_TOPIC = 'jarvis.hud';

const decoder = new TextDecoder();

function toLine(message: ReceivedMessage): ChatLine | null {
  const text = 'message' in message ? message.message : '';
  if (!text?.trim()) return null;
  let role: ChatLine['role'];
  if (message.type === 'userTranscript') role = 'user';
  else if (message.type === 'agentTranscript') role = 'agent';
  else role = message.from?.isLocal ? 'user' : 'agent';
  return { id: message.id, role, text, ts: message.timestamp };
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
    return () => {
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [room]);

  // Feed both voices into the analyser that drives the 3D core.
  const agentTrack = agent.microphoneTrack?.publication?.track as RemoteAudioTrack | undefined;
  const userTrack = session.local.microphoneTrack?.publication?.track as LocalAudioTrack | undefined;
  useEffect(() => attachTrack('agent', agentTrack), [agentTrack]);
  useEffect(() => attachTrack('user', isMicrophoneEnabled ? userTrack : undefined), [userTrack, isMicrophoneEnabled]);

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
    if (connectionState === ConnectionState.Connected && agent.isConnected) hud.addLog('ok', 'J.A.R.V.I.S. online');
    else if (connectionState === ConnectionState.Connected) hud.addLog('info', 'Link estabelecido · aguardando agente');
    else if (connectionState === ConnectionState.Reconnecting) hud.addLog('warn', 'Reconectando…');
    if (agent.state === 'failed') {
      const reasons = agent.failureReasons?.join(' ') || 'O agente não respondeu.';
      setError(`${reasons} Verifique se o worker está rodando (python agent.py dev).`);
      hud.addLog('error', 'Agente não respondeu');
    }
  }, [connectionState, agent.state, agent.isConnected, agent.failureReasons]);

  const lines = useMemo(() => messages.map(toLine).filter((line): line is ChatLine => line !== null), [messages]);

  const start = useCallback(async () => {
    setError(null);
    useHud.getState().addLog('info', 'Solicitando credenciais de acesso…');
    try {
      await session.start({ tracks: { microphone: { enabled: true } } });
    } catch (err) {
      setError(describeStartError(err));
      useHud.getState().addLog('error', 'Falha ao estabelecer link');
    }
  }, [session]);

  const stop = useCallback(async () => {
    await session.end();
    attachTrack('agent', undefined);
    attachTrack('user', undefined);
    useHud.getState().setActiveTool(null);
    useHud.getState().addLog('info', 'Sessão encerrada');
  }, [session]);

  const toggleMic = useCallback(async () => {
    try {
      await localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled);
    } catch (err) {
      setError(`Microfone indisponível: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [localParticipant, isMicrophoneEnabled]);

  const send = useCallback(
    async (text: string) => {
      await sendMessage(text);
    },
    [sendMessage],
  );

  const connected = connectionState !== ConnectionState.Disconnected;
  return useMemo(
    () => ({ mode, connected, lines, micEnabled: isMicrophoneEnabled, error, start, stop, toggleMic, send }),
    [mode, connected, lines, isMicrophoneEnabled, error, start, stop, toggleMic, send],
  );
}

const noop = async () => {};

/** Used while LiveKit is not configured: no session, no token requests. */
export const OFFLINE_LIVE: LiveJarvis = {
  mode: 'standby',
  connected: false,
  lines: [],
  micEnabled: false,
  error: null,
  start: noop,
  stop: noop,
  toggleMic: noop,
  send: noop,
};
