import { useCallback, useEffect, useRef, useState } from 'react';
import { playSleepChime, playWakeChime } from '../lib/chime';
import { useHud } from '../lib/hudStore';
import type { JarvisMode } from '../lib/types';
import { ACTIVE_MODES, hasPendingWork, noticeCard, noticeLogLevel, parseWakeEvent, silenceLeft } from '../lib/wake';

/** A wake heard while a freshly opened tab is still booting waits this long for the link. */
const WAKE_TTL_MS = 40_000;
/** The dock shows the silence countdown in its last seconds. */
const COUNTDOWN_MS = 10_000;
const TICK_MS = 500;

export interface WakeWord {
  /** JARVIS_WAKE_WORD=true and this tab is subscribed to the detector. */
  enabled: boolean;
  /** The detector process is talking to the server. */
  detector: boolean;
  /** The detector has the microphone open, waiting for "Jarvis". */
  listening: boolean;
  /** ...but that microphone delivers only silence (muted in Windows?). */
  micSilent: boolean;
  /** Seconds left before the link closes for silence, only in the last few seconds. */
  closingIn: number | null;
}

interface WakeOptions {
  /** /api/status says JARVIS_WAKE_WORD=true. */
  enabled: boolean;
  /** /api/status says JARVIS_PROACTIVE=true: notices arrive on the same stream and may open the link. */
  proactive: boolean;
  /** LiveKit is configured. */
  canConnect: boolean;
  /** The LiveKit session is mounted, so start() really connects. */
  ready: boolean;
  connected: boolean;
  busy: boolean;
  demo: boolean;
  mode: JarvisMode;
  error: string | null;
  lineCount: number;
  micLabel: string | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

function post(path: string, body: unknown) {
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).catch(() => undefined);
}

const isVisible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden';

/**
 * WAK-22: the local detector heard "Jarvis" → chime and connect the link; silence for
 * JARVIS_WAKE_SILENCE_SECONDS → close it, so the detector goes back to listening.
 */
export function useWakeWord(options: WakeOptions): WakeWord {
  const { enabled, proactive, canConnect, ready, connected, busy, demo, mode, error, lineCount, micLabel } = options;
  const [clientId] = useState(() => crypto.randomUUID());
  const [subscribed, setSubscribed] = useState(false);
  const [noticesOn, setNoticesOn] = useState(false);
  /** This link was opened by a notice: it closes after the silence even without the wake word. */
  const [noticeLink, setNoticeLink] = useState(false);
  const [reports, setReports] = useState(0);
  const [detector, setDetector] = useState({ online: false, listening: false, micSilent: false });
  const [silenceS, setSilenceS] = useState(0);
  const [wakeAt, setWakeAt] = useState<number | null>(null);
  const [closingIn, setClosingIn] = useState<number | null>(null);
  const [visible, setVisible] = useState(isVisible);

  const sessionActive = connected || busy;
  const latest = useRef({ sessionActive, demo, canConnect, mode, start: options.start, stop: options.stop });
  useEffect(() => {
    latest.current = { sessionActive, demo, canConnect, mode, start: options.start, stop: options.stop };
  });
  const attempt = useRef(false);
  const lastActivity = useRef(Date.now());

  const report = useCallback((result: 'connected' | 'failed' | 'ignored') => post('/api/wake/result', { client: clientId, result }), [clientId]);

  const onWake = useCallback(
    (score: number, reason?: 'notice') => {
      const state = latest.current;
      const hud = useHud.getState();
      if (state.sessionActive || state.demo) {
        void report('ignored');
        return;
      }
      if (!state.canConnect) {
        hud.addLog('warn', 'Ouvi “Jarvis”, mas o LiveKit não está configurado');
        void report('failed');
        return;
      }
      playWakeChime();
      if (reason === 'notice') {
        hud.addLog('ok', 'Aviso do Jarvis · abrindo o link');
        setNoticeLink(true);
      } else {
        hud.addLog('ok', `Palavra de ativação · “Jarvis” (${Math.round(score * 100)}%)`);
      }
      setWakeAt(Date.now());
    },
    [report],
  );

  // The server's stream: config, detector status, wakes and proactive notices.
  useEffect(() => {
    if ((!enabled && !proactive) || typeof EventSource === 'undefined') return;
    const source = new EventSource(`/api/wake/events?client=${clientId}`);
    source.onmessage = (message) => {
      const event = parseWakeEvent(message.data);
      if (!event) return;
      if (event.type === 'config') {
        setSubscribed(event.enabled);
        setNoticesOn(event.proactive ?? false);
        setSilenceS(event.silence_s);
        // The server knows this tab now: (re)send its state, also after a server restart.
        setReports((count) => count + 1);
      } else if (event.type === 'status') {
        setDetector({ online: event.detector, listening: event.listening, micSilent: event.mic_silent ?? false });
      } else if (event.type === 'notice') {
        const hud = useHud.getState();
        hud.pushCard('note', noticeCard(event));
        hud.addLog(noticeLogLevel(event.priority), `${event.title} · ${event.message}`);
      } else {
        onWake(event.score, event.reason);
      }
    };
    source.onerror = () => setDetector({ online: false, listening: false, micSilent: false });
    return () => {
      source.close();
      setSubscribed(false);
      setNoticesOn(false);
    };
  }, [enabled, proactive, clientId, onWake]);

  useEffect(() => {
    const onChange = () => setVisible(isVisible());
    document.addEventListener('visibilitychange', onChange);
    return () => document.removeEventListener('visibilitychange', onChange);
  }, []);

  // While a link is open (or opening) the detector releases the microphone.
  // A notice only opens the link when no conversation is already open (or opening) in this tab.
  useEffect(() => {
    if ((!subscribed && !noticesOn) || reports === 0) return;
    void post('/api/wake/hud', { client: clientId, session_active: sessionActive, visible, mic_label: micLabel });
  }, [subscribed, noticesOn, reports, clientId, sessionActive, visible, micLabel]);

  // Connect as soon as this tab can (a tab the server just opened is still booting).
  useEffect(() => {
    if (wakeAt === null) return;
    if (connected) {
      setWakeAt(null);
      void report('ignored');
      return;
    }
    if (ready && !busy) {
      setWakeAt(null);
      attempt.current = true;
      void latest.current.start();
      return;
    }
    const expire = window.setTimeout(() => {
      setWakeAt(null);
      void report('failed');
    }, Math.max(0, wakeAt + WAKE_TTL_MS - Date.now()));
    return () => window.clearTimeout(expire);
  }, [wakeAt, ready, busy, connected, report]);

  useEffect(() => {
    if (!connected && !busy && wakeAt === null) setNoticeLink(false);
  }, [connected, busy, wakeAt]);

  useEffect(() => {
    if (!attempt.current) return;
    if (connected) {
      attempt.current = false;
      void report('connected');
    } else if (error && !busy) {
      attempt.current = false;
      void report('failed');
    }
  }, [connected, error, busy, report]);

  // Anything that looks like conversation restarts the silence countdown.
  const userHeardAt = useHud((s) => s.userHeardAt);
  const activeTool = useHud((s) => s.activeTool);
  useEffect(() => {
    lastActivity.current = Date.now();
  }, [connected, userHeardAt, activeTool, lineCount, mode]);

  useEffect(() => {
    setClosingIn(null);
    if ((!subscribed && !noticeLink) || silenceS <= 0 || !connected || demo) return;
    const timer = window.setInterval(() => {
      const now = Date.now();
      const current = latest.current.mode;
      if (ACTIVE_MODES.has(current)) lastActivity.current = now;
      const left = silenceLeft({
        now,
        lastActivityAt: lastActivity.current,
        silenceMs: silenceS * 1000,
        mode: current,
        pendingWork: hasPendingWork(useHud.getState().cards, now),
      });
      if (left === null || left > COUNTDOWN_MS) {
        setClosingIn(null);
      } else if (left > 0) {
        setClosingIn(Math.ceil(left / 1000));
      } else {
        window.clearInterval(timer);
        playSleepChime();
        useHud.getState().addLog('info', `Link encerrado após ${silenceS} s de silêncio · diga “Jarvis” para chamar de novo`);
        void latest.current.stop();
      }
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [subscribed, noticeLink, silenceS, connected, demo]);

  return {
    enabled: subscribed,
    detector: detector.online,
    listening: detector.listening,
    micSilent: detector.micSilent,
    closingIn,
  };
}
