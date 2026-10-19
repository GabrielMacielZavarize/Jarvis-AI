import { RoomAudioRenderer, SessionProvider, StartAudio, useSession } from '@livekit/components-react';
import { ConnectionState, TokenSource } from 'livekit-client';
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityLog } from './components/ActivityLog';
import { BootSequence } from './components/BootSequence';
import { CameraIndicator } from './components/CameraIndicator';
import { CardStage } from './components/cards/CardStage';
import { ControlDock } from './components/ControlDock';
import { DictationIndicator } from './components/DictationIndicator';
import { ConversationPanel } from './components/ConversationPanel';
import { LanPanel } from './components/LanPanel';
import { PairingScreen } from './components/PairingScreen';
import { SystemPanel } from './components/SystemPanel';
import { TopBar } from './components/TopBar';
import { useCameraMonitor } from './hooks/useCameraMonitor';
import { useDemo } from './hooks/useDemo';
import { usePresence } from './hooks/usePresence';
import { useLanAccess } from './hooks/useLanAccess';
import { type LiveJarvis, OFFLINE_LIVE, useLiveJarvis } from './hooks/useLiveJarvis';
import { type StatusResult, useServerStatus } from './hooks/useServerStatus';
import { useWakeWord } from './hooks/useWakeWord';
import { homeFromTimezone } from './lib/geo';
import { useHud } from './lib/hudStore';
import type { JarvisMode } from './lib/types';
import { micLabelFor } from './lib/wake';

// three.js + postprocessing live in their own chunk; the boot sequence covers the load.
const Scene = lazy(() => import('./scene/Scene').then((module) => ({ default: module.Scene })));

const newRoomName = () => `jarvis-${crypto.randomUUID().slice(0, 8)}`;

export default function App() {
  // LAN-26: a phone that is not paired sees only the pairing screen (the server answers nothing else).
  const { access, refresh } = useLanAccess();
  if (access.state === 'loading') return null;
  if (access.state === 'unpaired') return <PairingScreen revoked={access.revoked} onPaired={() => void refresh()} />;
  return <JarvisApp local={access.state !== 'paired'} />;
}

function JarvisApp({ local }: { local: boolean }) {
  const status = useServerStatus();
  const [booted, setBooted] = useState(false);
  const [live, setLive] = useState<LiveJarvis>(OFFLINE_LIVE);
  const canConnect = status.state === 'ok' && status.status.livekit_configured;
  useCameraMonitor();

  return (
    <>
      {canConnect && <LiveSession onChange={setLive} />}
      <Hud status={status} booted={booted} live={canConnect ? live : OFFLINE_LIVE} local={local} />
      {!booted && <BootSequence onDone={() => setBooted(true)} />}
      <CameraIndicator />
      <DictationIndicator />
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
      {/* Only shows when the browser blocks the voice, e.g. a tab opened by "Jarvis" without a click yet. */}
      <StartAudio label="Clique para ouvir o Jarvis" className="btn btn--primary start-audio" />
    </SessionProvider>
  );
}

function LiveBridge({ onChange }: { onChange: (live: LiveJarvis) => void }) {
  const live = useLiveJarvis();
  useEffect(() => onChange(live), [live, onChange]);
  return null;
}

function Hud({ status, booted, live, local }: { status: StatusResult; booted: boolean; live: LiveJarvis; local: boolean }) {
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

  // WAK-22: saying "Jarvis" connects; silence closes the link and the detector listens again.
  // AGD-27: a meeting about to start connects too, so Jarvis can warn about it.
  const wake = useWakeWord({
    // Scheduled routines (ROT-24) and meeting reminders (AGD-27) open the link through the same
    // stream, even without the wake word.
    enabled: Boolean(server?.wake_word?.enabled || server?.routines?.enabled || server?.calendar?.reminders),
    proactive: server?.proactive ?? false,
    presence: server?.presence ?? false,
    canConnect,
    ready: canConnect && live !== OFFLINE_LIVE,
    connected: live.connected,
    busy,
    demo: demo.running,
    mode: live.mode,
    error: live.error,
    lineCount: live.lines.length,
    micLabel: micLabelFor(live.micDeviceId, live.micDevices),
    start,
    stop: live.stop,
  });
  const wakeListening = wake.enabled && wake.listening;
  // PRS-25: "Presente" / "Ausente há 5 min" in the Sistema panel.
  const presence = usePresence(server?.presence ?? false);

  // Global shortcuts: Space starts, M toggles the mic, Esc clears the projections.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = (event.target as HTMLElement)?.tagName === 'INPUT';
      if (event.key === 'Escape') {
        const hud = useHud.getState();
        if (hud.expandedId) hud.setExpanded(null);
        else hud.clearCards();
      }
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
          <span className="core-trigger__label">
            {busy ? 'Estabelecendo link' : wakeListening ? 'Diga “Jarvis” ou toque para inicializar' : 'Toque para inicializar'}
          </span>
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
            wake={wake.enabled ? wake : null}
            presence={presence}
          />
          {local && server?.lan && <LanPanel />}
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
            wakeListening={wakeListening}
            closingIn={wake.closingIn}
          />
        </div>
      </div>
    </main>
  );
}
