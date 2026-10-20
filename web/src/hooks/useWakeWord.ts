import { useCallback, useEffect, useRef, useState } from 'react';
import { playSleepChime, playWakeChime } from '../lib/chime';
import { useHud } from '../lib/hudStore';
import { getPrefs, setPrefs } from '../lib/prefs';
import { themeInfo } from '../lib/themes';
import type { JarvisMode } from '../lib/types';
import { playCue } from '../lib/sounds';
import {
  ACTIVE_MODES,
  hasPendingWork,
  noticeCard,
  noticeLogLevel,
  noticeToast,
  parseWakeEvent,
  silenceLeft,
  wakePersona,
  wakeWordLabel,
  wakeWordsLabel,
} from '../lib/wake';

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
  /** The detector has the microphone open, waiting for "Jarvis" (or "Friday"). */
  listening: boolean;
  /** Names the detector hears ("jarvis", "friday"); empty until it reports them. */
  words: string[];
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
  /** /api/status says JARVIS_PRESENCE=true: the webcam opens the link when the user comes back (PRS-25). */
  presence?: boolean;
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
 * ROT-24: a scheduled routine that came due arrives as the same wake, with its name.
 * PRS-25: the presence detector opens the link the same way when the user sits back down.
 * "Friday" heard with another persona on screen switches the theme before connecting: the server
 * has already saved that persona, so the agent starts as F.R.I.D.A.Y.
 */
export function useWakeWord(options: WakeOptions): WakeWord {
  const { enabled, proactive, presence = false, canConnect, ready, connected, busy, demo, mode, error, lineCount, micLabel } = options;
  const [clientId] = useState(() => crypto.randomUUID());
  /** The wake word is on (the Sistema panel shows the detector). */
  const [subscribed, setSubscribed] = useState(false);
  // False when the stream is open only for meeting reminders (AGD-27), without the detector.
  const [wakeWord, setWakeWord] = useState(true);
  const [noticesOn, setNoticesOn] = useState(false);
  /** This link was opened by a notice: it closes after the silence even without the wake word. */
  const [noticeLink, setNoticeLink] = useState(false);
  /** Presence (PRS-25) is on: the webcam opens links and silence closes them. */
  const [presenceOn, setPresenceOn] = useState(false);
  /** The tray icon (BAN-41) needs this tab's link state to show it and to close the link. */
  const [trayOn, setTrayOn] = useState(false);
  const [reports, setReports] = useState(0);
  const [detector, setDetector] = useState({ online: false, listening: false, micSilent: false, words: [] as string[] });
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
  const wordsRef = useRef<string[]>([]);
  useEffect(() => {
    wordsRef.current = detector.words;
  }, [detector.words]);

  const report = useCallback((result: 'connected' | 'failed' | 'ignored') => post('/api/wake/result', { client: clientId, result }), [clientId]);

  const onWake = useCallback(
    (score: number, routine?: string, reason?: 'calendar' | 'notice' | 'presence' | 'tray', word?: string, persona?: string) => {
      const byPresence = reason === 'presence';
      const heard = `“${wakeWordLabel(word)}”`;
      const state = latest.current;
      const hud = useHud.getState();
      if (state.sessionActive || state.demo) {
        void report('ignored');
        return;
      }
      if (!state.canConnect) {
        hud.addLog(
          'warn',
          routine
            ? `Rotina agendada “${routine}”, mas o LiveKit não está configurado`
            : byPresence
              ? 'Você voltou, mas o LiveKit não está configurado'
              : `Ouvi ${heard}, mas o LiveKit não está configurado`,
        );
        void report('failed');
        return;
      }
      const switchTo = wakePersona(persona, getPrefs().theme);
      if (switchTo) {
        setPrefs({ theme: switchTo });
        hud.addLog('info', `Persona · ${themeInfo(switchTo).label}, chamada pelo nome`);
      }
      playWakeChime();
      if (routine) {
        hud.addLog('ok', `Rotina agendada · “${routine}”`);
        hud.pushToast({ level: 'info', title: 'Rotina agendada', message: routine, code: 'ROT-24' });
      } else if (reason === 'calendar') {
        hud.addLog('ok', 'Aviso da agenda · reunião chegando');
        hud.pushToast({ level: 'warn', title: 'Reunião chegando', message: 'O Jarvis vai avisar os detalhes.', code: 'AGD-27' });
      }
      else if (reason === 'notice') {
        hud.addLog('ok', 'Aviso do Jarvis · abrindo o link');
        setNoticeLink(true);
      } else if (byPresence) hud.addLog('ok', 'Presença · você voltou, abrindo o link');
      else if (reason === 'tray') hud.addLog('ok', 'Bandeja · abrindo o link');
      else hud.addLog('ok', `Palavra de ativação · ${heard} (${Math.round(score * 100)}%)`);
      setWakeAt(Date.now());
    },
    [report],
  );

  // The server's stream: config, detector status, wakes and proactive notices.
  useEffect(() => {
    if ((!enabled && !proactive && !presence) || typeof EventSource === 'undefined') return;
    const source = new EventSource(`/api/wake/events?client=${clientId}`);
    source.onmessage = (message) => {
      const event = parseWakeEvent(message.data);
      if (!event) return;
      if (event.type === 'config') {
        setSubscribed(event.enabled);
        setWakeWord(event.wake_word ?? true);
        setNoticesOn(event.proactive ?? false);
        setPresenceOn(event.presence ?? false);
        setTrayOn(event.tray ?? false);
        setSilenceS(event.silence_s);
        // The server knows this tab now: (re)send its state, also after a server restart.
        setReports((count) => count + 1);
      } else if (event.type === 'status') {
        setDetector({
          online: event.detector,
          listening: event.listening,
          micSilent: event.mic_silent ?? false,
          words: event.words ?? [],
        });
      } else if (event.type === 'notice') {
        const hud = useHud.getState();
        hud.pushCard('note', noticeCard(event));
        hud.pushToast(noticeToast(event));
        // Spoken notices have Jarvis's voice and the link chime; the silent ones get a sound of their own.
        if (event.route === 'hud') playCue('notice');
        hud.addLog(noticeLogLevel(event.priority), `${event.title} · ${event.message}`);
      } else if (event.type === 'sleep') {
        const state = latest.current;
        if (!state.sessionActive || state.demo) return;
        playSleepChime();
        useHud.getState().addLog('info', 'Bandeja · link encerrado');
        void state.stop();
      } else {
        onWake(event.score, event.routine, event.reason, event.word, event.persona);
      }
    };
    source.onerror = () => setDetector({ online: false, listening: false, micSilent: false, words: [] });
    return () => {
      source.close();
      setSubscribed(false);
      setWakeWord(true);
      setNoticesOn(false);
      setPresenceOn(false);
      setTrayOn(false);
    };
  }, [enabled, proactive, presence, clientId, onWake]);

  useEffect(() => {
    const onChange = () => setVisible(isVisible());
    document.addEventListener('visibilitychange', onChange);
    return () => document.removeEventListener('visibilitychange', onChange);
  }, []);

  // While a link is open (or opening) the detector releases the microphone.
  // A notice only opens the link when no conversation is already open (or opening) in this tab.
  useEffect(() => {
    if ((!subscribed && !noticesOn && !presenceOn && !trayOn) || reports === 0) return;
    void post('/api/wake/hud', { client: clientId, session_active: sessionActive, visible, mic_label: micLabel });
  }, [subscribed, noticesOn, presenceOn, trayOn, reports, clientId, sessionActive, visible, micLabel]);

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
    if ((!subscribed && !noticeLink && !presenceOn) || silenceS <= 0 || !connected || demo) return;
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
        const again = subscribed && wakeWord ? ` · diga ${wakeWordsLabel(wordsRef.current)} para chamar de novo` : '';
        useHud.getState().addLog('info', `Link encerrado após ${silenceS} s de silêncio${again}`);
        void latest.current.stop();
      }
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [subscribed, noticeLink, presenceOn, silenceS, connected, demo]);

  return {
    enabled: subscribed && wakeWord,
    detector: detector.online,
    listening: detector.listening,
    micSilent: detector.micSilent,
    words: detector.words,
    closingIn,
  };
}
