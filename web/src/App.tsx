import { RoomAudioRenderer, SessionProvider, useSession } from '@livekit/components-react';
import { ConnectionState, TokenSource } from 'livekit-client';
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityLog } from './components/ActivityLog';
import { BootSequence } from './components/BootSequence';
import { CardStage } from './components/cards/CardStage';
import { ControlDock } from './components/ControlDock';
import { ConversationPanel } from './components/ConversationPanel';
import { SystemPanel } from './components/SystemPanel';
import { TopBar } from './components/TopBar';
import { useDemo } from './hooks/useDemo';
import { type LiveJarvis, OFFLINE_LIVE, useLiveJarvis } from './hooks/useLiveJarvis';
import { type StatusResult, useServerStatus } from './hooks/useServerStatus';
import { homeFromTimezone } from './lib/geo';
import { useHud } from './lib/hudStore';
import type { JarvisMode } from './lib/types';

// three.js + postprocessing live in their own chunk; the boot sequence covers the load.
const Scene = lazy(() => import('./scene/Scene').then((module) => ({ default: module.Scene })));

const newRoomName = () => `jarvis-${crypto.randomUUID().slice(0, 8)}`;

export default function App() {
  const status = useServerStatus();
  const [booted, setBooted] = useState(false);
  const [live, setLive] = useState<LiveJarvis>(OFFLINE_LIVE);
  const canConnect = status.state === 'ok' && status.status.livekit_configured;

  return (
    <>
      {canConnect && <LiveSession onChange={setLive} />}
      <Hud status={status} booted={booted} live={canConnect ? live : OFFLINE_LIVE} />
      {!booted && <BootSequence onDone={() => setBooted(true)} />}
    </>
  );
}

/** Owns the LiveKit session; only mounted once the backend can issue tokens. */
function LiveSession({ onChange }: { onChange: (live: LiveJarvis) => void }) {
  const tokenSource = useMemo(() => TokenSource.endpoint('/api/token'), []);
  // A fresh room per session guarantees the agent is dispatched again on reconnect
  // (agent dispatch only happens when LiveKit creates the room).
  const [roomName, setRoomName] = useState(newRoomName);
  const session = useSession(tokenSource, { agentName: 'jarvis', participantName: 'Operador', roomName });
  const wasConnected = useRef(false);

  useEffect(() => {
    if (session.connectionState === ConnectionState.Connected) {
      wasConnected.current = true;
    } else if (session.connectionState === ConnectionState.Disconnected && wasConnected.current) {
      wasConnected.current = false;
      setRoomName(newRoomName());
    }
  }, [session.connectionState]);

  return (
    <SessionProvider session={session}>
      <LiveBridge onChange={onChange} />
      <RoomAudioRenderer />
    </SessionProvider>
  );
}

function LiveBridge({ onChange }: { onChange: (live: LiveJarvis) => void }) {
  const live = useLiveJarvis();
  useEffect(() => onChange(live), [live, onChange]);
  return null;
}

function Hud({ status, booted, live }: { status: StatusResult; booted: boolean; live: LiveJarvis }) {
  const demo = useDemo();
  const [busy, setBusy] = useState(false);
  const [sessionStart, setSessionStart] = useState<number | null>(null);
  const activeTool = useHud((s) => s.activeTool);

  const server = status.state === 'ok' ? status.status : null;
  const canConnect = server?.livekit_configured ?? false;
  const offline = status.state === 'unreachable' || (server !== null && !server.ready);

  let mode: JarvisMode = demo.running ? demo.mode : live.mode;
  if (!demo.running && !live.connected && offline) mode = 'offline';
  if (busy && mode === 'standby') mode = 'connecting';
  const connected = demo.running || live.connected;
  const lines = demo.running ? demo.lines : live.lines;

  useEffect(() => useHud.getState().setMode(mode), [mode]);

  // The 3D globe draws connections from the user's city (JARVIS_HOME_CITY) or a timezone guess.
  const home = server?.home;
  useEffect(() => {
    useHud.getState().setHome(home ? { name: home.name, lat: home.latitude, lon: home.longitude } : homeFromTimezone());
  }, [home]);

  // While the model thinks, show the round-trip to it on the globe.
  const modelHost = server?.backend?.startsWith('openai') ? 'api.openai.com' : 'generativelanguage.googleapis.com';
  useEffect(() => {
    if (mode === 'thinking') useHud.getState().addLinks([modelHost], 'model');
  }, [mode, modelHost]);
  useEffect(() => setSessionStart(connected ? Date.now() : null), [connected]);

  const start = async () => {
    if (demo.running || live.connected || busy) return;
    setBusy(true);
    try {
      await live.start();
    } finally {
      setBusy(false);
    }
  };

  const stop = () => (demo.running ? demo.stop() : void live.stop());

  // Global shortcuts: Space starts, M toggles the mic, Esc clears the projections.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = (event.target as HTMLElement)?.tagName === 'INPUT';
      if (event.key === 'Escape') useHud.getState().clearCards();
      if (typing) return;
      if (event.code === 'Space' && !connected && canConnect) {
        event.preventDefault();
        void start();
      }
      if (event.key.toLowerCase() === 'm' && live.connected) void live.toggleMic();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  return (
    <main className="app" data-mode={mode}>
      <Suspense fallback={null}>
        <Scene visible={booted} />
      </Suspense>
      <div className="fx fx--sweep" />
      <div className="fx fx--scanlines" />
      <div className="fx fx--frame" />

      {booted && !connected && canConnect && (
        <button type="button" className="core-trigger" onClick={() => void start()} aria-label="Inicializar o Jarvis">
          <span className="core-trigger__label">{busy ? 'Estabelecendo link' : 'Toque para inicializar'}</span>
        </button>
      )}

      <div className="hud">
        <div className="hud__top">
          <TopBar
            mode={mode}
            status={server}
            connected={connected}
            micEnabled={live.micEnabled}
            demo={demo.running}
            sessionStart={sessionStart}
          />
        </div>

        <aside className="hud__left">
          <SystemPanel
            mode={mode}
            status={status}
            demo={demo.running}
            connected={live.connected}
            micEnabled={live.micEnabled}
            microphone={{ devices: live.micDevices, deviceId: live.micDeviceId, onSelect: (id) => void live.selectMic(id) }}
          />
          <CardStage enabledTools={server?.tools ?? null} />
        </aside>

        <aside className="hud__right">
          <ConversationPanel
            lines={lines}
            thinking={mode === 'thinking' || activeTool !== null}
            canSend={live.connected && !demo.running}
            onSend={live.send}
          />
          {live.error && !demo.running && (
            <div className="notice" role="alert">
              <strong>Atenção.</strong> {live.error}
            </div>
          )}
          <ActivityLog />
        </aside>

        <div className="hud__dock">
          <ControlDock
            mode={mode}
            connected={live.connected}
            busy={busy}
            micEnabled={live.micEnabled}
            demo={demo.running}
            canConnect={canConnect}
            onStart={() => void start()}
            onStop={stop}
            onToggleMic={() => void live.toggleMic()}
            onDemo={demo.start}
          />
        </div>
      </div>
    </main>
  );
}
