import { RoomAudioRenderer, SessionProvider, StartAudio, useSession } from '@livekit/components-react';
import { ConnectionState, TokenSource } from 'livekit-client';
import { lazy, type ReactNode, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityLog } from './components/ActivityLog';
import { AmbientMode } from './components/AmbientMode';
import { BootSequence } from './components/BootSequence';
import { CameraIndicator } from './components/CameraIndicator';
import { CardStage } from './components/cards/CardStage';
import { ControlDock } from './components/ControlDock';
import { DictationIndicator } from './components/DictationIndicator';
import { GesturesPanel } from './components/GesturesPanel';
import { ConversationPanel } from './components/ConversationPanel';
import { LanPanel } from './components/LanPanel';
import { PairingScreen } from './components/PairingScreen';
import { SystemPanel } from './components/SystemPanel';
import { Toasts } from './components/Toasts';
import { TopBar } from './components/TopBar';
import { useCameraMonitor } from './hooks/useCameraMonitor';
import { useDemo } from './hooks/useDemo';
import { useIdle } from './hooks/useIdle';
import { usePanelDrag } from './hooks/usePanelDrag';
import { usePersonaSync } from './hooks/usePersonaSync';
import { useReactorHum } from './hooks/useReactorHum';
import { useSettledMode } from './hooks/useSettledMode';
import { usePresence } from './hooks/usePresence';
import { useLanAccess } from './hooks/useLanAccess';
import { type LiveJarvis, OFFLINE_LIVE, useLiveJarvis } from './hooks/useLiveJarvis';
import { type StatusResult, useServerStatus } from './hooks/useServerStatus';
import { useWakeWord } from './hooks/useWakeWord';
import { AMBIENT_AFTER_MS } from './lib/ambient';
import { mcpHint } from './lib/catalog';
import { homeFromTimezone } from './lib/geo';
import { useHud } from './lib/hudStore';
import { type PanelId, usePrefs } from './lib/prefs';
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
  // The theme is also the agent's persona and voice: keep it in step with the server.
  usePersonaSync(status.state === 'ok' ? status.status.persona : undefined);

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
  const cinema = useHud((s) => s.cinema);
  const prefs = usePrefs();

  const server = status.state === 'ok' ? status.status : null;
  const canConnect = server?.livekit_configured ?? false;
  const offline = status.state === 'unreachable' || (server !== null && !server.ready);

  let rawMode: JarvisMode = demo.running ? demo.mode : live.mode;
  if (!demo.running && !live.connected && offline) rawMode = 'offline';
  if (busy && rawMode === 'standby') rawMode = 'connecting';
  // What the HUD paints: a quick "thinking" or a pause between sentences does not repaint it.
  const mode = useSettledMode(rawMode);
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
  // Ambient mode: a few idle minutes without a link (never during a session or the simulation).
  const ambient = useIdle(AMBIENT_AFTER_MS, prefs.ambient && booted && !connected && !busy);
  // The hum only plays with the reactor awake: a link or the simulation, never on the idle screen.
  useReactorHum(booted && connected);
  // PRS-25: "Presente" / "Ausente há 5 min" in the Sistema panel.
  const presence = usePresence(server?.presence ?? false);

  // Every panel of the side columns; Ajustes and dragging a header decide which column and order.
  const drag = usePanelDrag();
  const panels: Record<PanelId, ReactNode> = {
    system: (
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
    ),
    lan: local && server?.lan ? <LanPanel /> : null,
    cards: <CardStage enabledTools={server?.tools ?? null} hints={{ mcp_status: mcpHint(server?.mcp) }} />,
    conversation: (
      <>
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
      </>
    ),
    gestures: server?.gestures ? <GesturesPanel connected={live.connected && !demo.running} /> : null,
    log: <ActivityLog />,
  };

  // Global shortcuts: Space starts, M toggles the mic, Esc clears the projections.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes((event.target as HTMLElement)?.tagName);
      if (event.key === 'Escape') {
        const hud = useHud.getState();
        if (hud.expandedId) hud.setExpanded(null);
        else if (hud.cinema) hud.setCinema(false);
        else hud.clearCards();
      }
      if (typing) return;
      if (event.key.toLowerCase() === 'f' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        useHud.getState().setCinema(!useHud.getState().cinema);
      }
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
    <main className="app" data-mode={mode} data-cinema={cinema || undefined} data-ambient={ambient || undefined}>
      <Suspense fallback={null}>
        <Scene visible={booted} />
      </Suspense>
      <div className="fx fx--ambient" />
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

      <div className={`hud ${booted ? 'hud--online' : ''}`}>
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

        {(['left', 'right'] as const).map((column) => (
          <aside key={column} className={`hud__${column}`}>
            {prefs.layout[column].map((id) => (
              <div
                key={id}
                className={`slot ${drag.dragging === id ? 'slot--dragging' : ''}`}
                data-slot={id}
                onPointerDown={drag.onPointerDown(id)}
              >
                {panels[id]}
              </div>
            ))}
          </aside>
        ))}
        {drag.target && (
          <i className="drop-line" style={{ top: drag.target.top, left: drag.target.left, width: drag.target.width }} aria-hidden />
        )}

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
            lines={lines}
            wakeListening={wakeListening}
            closingIn={wake.closingIn}
          />
        </div>
      </div>
      <AmbientMode active={ambient} wakeWord={wake.enabled} />
      <Toasts />
    </main>
  );
}
