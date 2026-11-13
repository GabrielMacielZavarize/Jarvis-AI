import { lazy, type ReactNode, startTransition, Suspense, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ActivityLog } from './components/ActivityLog';
import { BootSequence } from './components/BootSequence';
import { CameraIndicator } from './components/CameraIndicator';
import { CardStage } from './components/cards/CardStage';
import { ControlDock } from './components/ControlDock';
import { DictationIndicator } from './components/DictationIndicator';
import { BriefingPanel } from './components/BriefingPanel';
import { ConversationPanel } from './components/ConversationPanel';
import { NavTabs } from './components/NavTabs';
import { PairingScreen } from './components/PairingScreen';
import { Toasts } from './components/Toasts';
import { TopBar } from './components/TopBar';
import { useCameraMonitor } from './hooks/useCameraMonitor';
import { useDemo } from './hooks/useDemo';
import { useIdle } from './hooks/useIdle';
import { usePanelDrag } from './hooks/usePanelDrag';
import { usePersonaSync } from './hooks/usePersonaSync';
import { useReactorHum } from './hooks/useReactorHum';
import { useSettledMode } from './hooks/useSettledMode';
import { useSilentMicrophone } from './hooks/useSilentMicrophone';
import { usePresence } from './hooks/usePresence';
import { useLanAccess } from './hooks/useLanAccess';
import { type LiveJarvis, OFFLINE_LIVE } from './hooks/liveState';
import { type StatusResult, useServerStatus } from './hooks/useServerStatus';
import { useWakeWord } from './hooks/useWakeWord';
import { AMBIENT_AFTER_MS } from './lib/ambient';
import { homeFromTimezone } from './lib/geo';
import { useFocus } from './lib/focus';
import { useFocusSync } from './hooks/useFocusSync';
import { useHud } from './lib/hudStore';
import { DEFAULT_LAYOUT, type PanelId, setPrefs, usePrefs } from './lib/prefs';
import type { JarvisMode } from './lib/types';
import { preloadCardBodies } from './components/cards/CardBody';
import { type ViewId, viewForKey } from './lib/views';
import { micLabelFor } from './lib/wake';

// three.js + postprocessing live in their own chunk; the boot sequence covers the load.
const Scene = lazy(() => import('./scene/Scene').then((module) => ({ default: module.Scene })));

// O que não aparece na abertura vem sob demanda, cada coisa no seu pedaço do pacote: as áreas fora do
// Painel, a paleta de comandos, o modo ambiente e o LiveKit (só quando o servidor pode conectar).
const DayView = lazy(() => import('./components/DayView').then((module) => ({ default: module.DayView })));
const EyeView = lazy(() => import('./components/EyeView').then((module) => ({ default: module.EyeView })));
const SystemView = lazy(() => import('./components/SystemView').then((module) => ({ default: module.SystemView })));
const SettingsView = lazy(() => import('./components/SettingsView').then((module) => ({ default: module.SettingsView })));
const loadPalette = () => import('./components/CommandPalette').then((module) => ({ default: module.CommandPalette }));
const CommandPalette = lazy(loadPalette);
const AmbientMode = lazy(() => import('./components/AmbientMode').then((module) => ({ default: module.AmbientMode })));
const LiveSession = lazy(() => import('./components/LiveSession'));

/**
 * A área que está na tela. Ao trocar para uma que ainda não foi baixada, a área anterior continua
 * até o código chegar e só então a nova entra (uma transição do React): nada de tela vazia no meio.
 * `pending` é o intervalo de espera, para o HUD mostrar o cursor de carregando.
 */
function useShownView(target: ViewId): { shown: ViewId; pending: boolean } {
  const [shown, setShown] = useState(target);
  useEffect(() => {
    startTransition(() => setShown(target));
  }, [target]);
  return { shown, pending: shown !== target };
}

/**
 * A paleta é pequena (uns 4 kB) e quem aperta Ctrl+K já sai digitando: ela é baixada logo depois da
 * abertura, fora do pacote principal, e montada fechada. Assim a primeira letra não se perde.
 */
function usePaletteReady(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    void loadPalette().then(() => alive && setReady(true));
    return () => {
      alive = false;
    };
  }, []);
  return ready;
}

/** "Pular para o conteúdo": leva o foco ao primeiro painel da área aberta (ou ao dock, no modo cinema). */
function skipToContent(event: React.MouseEvent) {
  event.preventDefault();
  const target = document.getElementById('conteudo') ?? document.querySelector<HTMLElement>('.hud__dock button');
  target?.focus();
}

/** Fica montado depois da primeira abertura, para a saída animada de uma paleta/ambiente já visto. */
function useEverTrue(value: boolean): boolean {
  const [seen, setSeen] = useState(value);
  useEffect(() => {
    if (value) setSeen(true);
  }, [value]);
  return seen || value;
}

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
      {canConnect && (
        <Suspense fallback={null}>
          <LiveSession onChange={setLive} />
        </Suspense>
      )}
      <Hud status={status} booted={booted} live={canConnect ? live : OFFLINE_LIVE} local={local} />
      {!booted && <BootSequence onDone={() => setBooted(true)} />}
      <CameraIndicator />
      <DictationIndicator />
    </>
  );
}

function Hud({ status, booted, live, local }: { status: StatusResult; booted: boolean; live: LiveJarvis; local: boolean }) {
  const demo = useDemo();
  const [busy, setBusy] = useState(false);
  const [sessionStart, setSessionStart] = useState<number | null>(null);
  const activeTool = useHud((s) => s.activeTool);
  const cinema = useHud((s) => s.cinema);
  const wantedView = useHud((s) => s.view);
  const { shown: view, pending: viewPending } = useShownView(wantedView);
  const palette = useHud((s) => s.palette);
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
    enabled: Boolean(server?.wake_word?.enabled || server?.routines?.enabled || server?.calendar?.reminders || server?.tray),
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
  const ambientSeen = useEverTrue(ambient);
  const paletteReady = usePaletteReady();
  const paletteSeen = useEverTrue(palette) || paletteReady;
  // Os painéis projetados trazem o próprio pedaço de código: baixa antes da primeira projeção.
  useEffect(() => {
    if (connected || activeTool) preloadCardBodies();
  }, [connected, activeTool]);
  // The hum only plays with the reactor awake: a link or the simulation, never on the idle screen.
  useReactorHum(booted && connected);
  // PRS-25: "Presente" / "Ausente há 5 min" in the Sistema panel.
  const presence = usePresence(server?.presence ?? false);

  // FOC-47: o servidor conta a sessão de foco; o HUD só a lê (a cada poucos segundos, e já quando o
  // bloco passa do fim) e mostra. Com o Dia a dia desligado não há sessão para ler.
  useFocusSync(server?.day === true);

  const focusRunning = useFocus((s) => s.focus.running);
  const micSilent = useSilentMicrophone(live.connected && !demo.running && live.micEnabled);
  const sendText = (text: string) => void live.send(text);

  // Os painéis das colunas do Painel; arrastar um cabeçalho decide a coluna e a ordem.
  const drag = usePanelDrag();
  const panels: Record<PanelId, ReactNode> = {
    briefing: (
      <BriefingPanel
        status={status}
        canSend={live.connected && !demo.running}
        demo={demo.running}
        onSend={sendText}
        wakeListening={wakeListening}
        micSilent={micSilent}
      />
    ),
    cards: <CardStage />,
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
    log: <ActivityLog />,
  };

  // O que a paleta de comandos (Ctrl+K) precisa para rodar cada comando.
  const paletteContext = {
    connected,
    demo: demo.running,
    canConnect,
    busy,
    micEnabled: live.micEnabled,
    prefs,
    enabledTools: server?.tools ?? null,
    start: () => void start(),
    stop,
    toggleMic: () => void live.toggleMic(),
    startDemo: demo.start,
    setPrefs,
    resetLayout: () => setPrefs({ layout: DEFAULT_LAYOUT }),
    send: sendText,
    focusRunning,
    startFocus: () => void useFocus.getState().start(),
    stopFocus: () => void useFocus.getState().stop(),
  };

  // Global shortcuts: Space starts, M toggles the mic, Esc clears the projections.
  // O ouvinte é registrado uma vez só e chama sempre a versão mais nova da função: religá-lo a cada
  // renderização deixava um intervalo sem ouvinte (a troca de área em transição demora a limpar os
  // efeitos) e uma tecla apertada logo depois de outra se perdia.
  const onKeyRef = useRef<(event: KeyboardEvent) => void>(() => undefined);
  useLayoutEffect(() => {
    onKeyRef.current = (event: KeyboardEvent) => {
      const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes((event.target as HTMLElement)?.tagName);
      const hud = useHud.getState();
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        hud.setPalette(!hud.palette);
        return;
      }
      // Com a paleta aberta as teclas são dela (o Esc inclusive).
      if (hud.palette) return;
      if (event.key === 'Escape') {
        if (hud.expandedId) hud.setExpanded(null);
        else if (hud.cinema) hud.setCinema(false);
        else if (hud.view !== 'home') hud.setView('home');
        else hud.clearCards();
      }
      if (typing) return;
      const target = event.ctrlKey || event.metaKey || event.altKey ? null : viewForKey(event.key);
      if (target) hud.setView(target);
      if (event.key.toLowerCase() === 'f' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        useHud.getState().setCinema(!useHud.getState().cinema);
      }
      if (event.code === 'Space' && !connected && canConnect) {
        event.preventDefault();
        void start();
      }
      if (event.key.toLowerCase() === 'm' && live.connected) void live.toggleMic();
    };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => onKeyRef.current(event);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <main className="app" data-mode={mode} data-view={view} data-cinema={cinema || undefined} data-ambient={ambient || undefined} data-pending={viewPending || undefined}>
      {booted && (
        <a className="skip-link" href="#conteudo" onClick={skipToContent}>
          Pular para o conteúdo
        </a>
      )}
      <Suspense fallback={null}>
        <Scene visible={booted} />
      </Suspense>
      <div className="fx fx--ambient" />
      <div className="fx fx--sweep" />
      <div className="fx fx--scanlines" />
      <div className="fx fx--frame" />

      {booted && !connected && canConnect && view === 'home' && (
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

        {view === 'home' &&
          (['left', 'right'] as const).map((column) => (
            <aside key={column} className={`hud__${column}`} id={column === 'left' ? 'conteudo' : undefined} tabIndex={column === 'left' ? -1 : undefined}>
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
        {drag.target && view === 'home' && (
          <i className="drop-line" style={{ top: drag.target.top, left: drag.target.left, width: drag.target.width }} aria-hidden />
        )}
        <Suspense fallback={null}>
          {view === 'day' && <DayView server={server} local={local} />}
          {view === 'eye' && <EyeView server={server} />}
          {view === 'system' && (
            <SystemView
              mode={mode}
              status={status}
              demo={demo.running}
              connected={live.connected}
              micEnabled={live.micEnabled}
              wake={wake.enabled ? wake : null}
              presence={presence}
              local={local}
            />
          )}
          {view === 'settings' && (
            <SettingsView
              microphone={{ devices: live.micDevices, deviceId: live.micDeviceId, onSelect: (id) => void live.selectMic(id) }}
              demo={demo.running}
            />
          )}
        </Suspense>

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
      {booted && <NavTabs variant="bar" />}
      {ambientSeen && (
        <Suspense fallback={null}>
          <AmbientMode active={ambient} wakeWord={wake.enabled} />
        </Suspense>
      )}
      {paletteSeen && (
        <Suspense fallback={null}>
          <CommandPalette context={paletteContext} osint={server?.osint?.enabled ?? false} />
        </Suspense>
      )}
      <Toasts />
    </main>
  );
}
