import { type RefObject, useEffect, useRef, useState } from 'react';
import { useClock } from '../../hooks/useClock';
import { refreshCamera } from '../../hooks/useCameraMonitor';
import { CAMERA_STREAM_URL, feedSpecs, feedStatus, turnCameraOff } from '../../lib/camera';
import { gestureCommand, liveFromReply, STATE_LABELS } from '../../lib/gestures';
import { useHud } from '../../lib/hudStore';
import { presenceLabel } from '../../lib/presence';
import type { CameraData } from '../../lib/types';
import {
  cameraAnswer,
  coverMap,
  HAND_CONNECTIONS,
  type HandFrame,
  handPixels,
  isStale,
  loadMirror,
  poseLabel,
  saveMirror,
  STATE_TONES,
} from '../../lib/vision';

const stamp = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});
const clock = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });

function Reticle() {
  return (
    <svg className="cam__reticle" viewBox="0 0 100 100" aria-hidden>
      <circle cx="50" cy="50" r="30" className="cam__ring" />
      <circle cx="50" cy="50" r="38" className="cam__arc" />
      <circle cx="50" cy="50" r="1.4" />
      <path d="M50 8v12M50 80v12M8 50h12M80 50h12" />
      <path d="M41 50h5M54 50h5M50 41v5M50 54v5" className="cam__fine" />
    </svg>
  );
}

function cssColor(element: Element, variable: string): string {
  return getComputedStyle(element).getPropertyValue(variable).trim() || '#7fe8ff';
}

/** Draws the hands the gesture engine sees over the feed, straight from the store (no React re-render per frame). */
function HandOverlay({ feed, mirrored }: { feed: RefObject<HTMLImageElement | null>; mirrored: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    let drawn: HandFrame | null | undefined;
    let wasStale = true;
    let raf = 0;

    const draw = () => {
      raf = window.requestAnimationFrame(draw);
      const frame = useHud.getState().hands;
      const stale = isStale(frame, Date.now());
      const width = node.clientWidth;
      const height = node.clientHeight;
      const ratio = window.devicePixelRatio || 1;
      const resized = node.width !== Math.round(width * ratio) || node.height !== Math.round(height * ratio);
      if (frame === drawn && stale === wasStale && !resized) return;
      drawn = frame;
      wasStale = stale;
      if (resized) {
        node.width = Math.round(width * ratio);
        node.height = Math.round(height * ratio);
      }
      const context = node.getContext('2d');
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      if (!frame || stale || frame.hands.length === 0) return;

      const image = feed.current;
      const map = coverMap(width, height, image?.naturalWidth ?? 16, image?.naturalHeight ?? 9);
      const color = cssColor(node, STATE_TONES[frame.state]);
      const joint = cssColor(node, '--c-ok');
      frame.hands.forEach((hand, index) => {
        const points = handPixels(hand, map, mirrored);
        context.globalAlpha = index === 0 ? 1 : 0.55; // a outra mão só conta nos gestos de duas mãos
        context.strokeStyle = color;
        context.lineWidth = 2.5;
        context.lineCap = 'round';
        context.shadowColor = color;
        context.shadowBlur = 8;
        context.beginPath();
        for (const [start, end] of HAND_CONNECTIONS) {
          context.moveTo(...points[start]);
          context.lineTo(...points[end]);
        }
        context.stroke();
        context.shadowBlur = 0;
        context.fillStyle = joint;
        points.forEach(([x, y], point) => {
          context.beginPath();
          context.arc(x, y, point === 4 || point === 8 ? 4.5 : 2.6, 0, Math.PI * 2);
          context.fill();
        });
      });
      context.globalAlpha = 1;
    };
    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }, [feed, mirrored]);

  return <canvas ref={canvas} className="cam__hands" aria-hidden />;
}

/** What the gesture engine is saying right now, over the feed (the same text as the desktop overlay). */
function GestureBanner() {
  const now = useClock(500);
  const frame = useHud((s) => s.hands);
  if (isStale(frame, now) || !frame) return null;
  const pose = poseLabel(frame.pose);
  const tone = frame.tone ?? 'info';
  return (
    <>
      {pose && frame.hands.length > 0 && (
        <div className="cam__pose" role="status">
          <span aria-hidden>{pose.glyph}</span> {pose.name}
        </div>
      )}
      {frame.title && (
        <div className={`cam__banner cam__banner--${tone}`}>
          <strong>{frame.title}</strong>
          {frame.detail && <small>{frame.detail}</small>}
          {frame.progress !== null && (
            <i className="cam__progress" aria-hidden>
              <b style={{ width: `${Math.round(frame.progress * 100)}%` }} />
            </i>
          )}
        </div>
      )}
    </>
  );
}

/** You, your hand and what Jarvis saw, under the feed. */
function VisionReadouts({ data }: { data: CameraData }) {
  const now = useClock(1000);
  const presence = useHud((s) => s.presence);
  const gestures = useHud((s) => s.gestures);
  const frame = useHud((s) => s.hands);
  const transcript = useHud((s) => s.transcript);

  const running = gestures.state !== 'unknown' && gestures.state !== 'off';
  const seeing = running && !isStale(frame, now) && (frame?.hands.length ?? 0) > 0;
  const answer = cameraAnswer(transcript, data.takenAt);
  const you = presence ? presenceLabel(presence, now) : null;
  const asked = data.question ? `“${data.question}”` : null;

  return (
    <div className="vision">
      <section className="vision__cell">
        <h4>Você</h4>
        <p className={you?.ok ? 'vision__ok' : undefined}>{you ? you.text : 'Presença desligada'}</p>
      </section>
      <section className="vision__cell">
        <h4>Gestos</h4>
        <p className={running ? 'vision__ok' : undefined}>
          {STATE_LABELS[gestures.state]}
          {running && <small> · {seeing ? `vendo sua mão${frame?.fps ? ` · ${frame.fps} q/s` : ''}` : 'sem mão no quadro'}</small>}
        </p>
      </section>
      <section className="vision__cell">
        <h4>Jarvis viu{data.snapshot && data.takenAt ? ` · ${clock.format(data.takenAt)}` : ''}</h4>
        {asked && <p className="vision__when">{asked}</p>}
        {data.snapshot ? (
          <p className="vision__answer" title={[asked, answer].filter(Boolean).join(' ') || undefined}>
            {answer ?? 'Analisando a foto…'}
          </p>
        ) : (
          <p className="vision__hint">Só quando você pede: “Jarvis, o que você está vendo?”</p>
        )}
      </section>
    </div>
  );
}

/** Turns the gestures on or off from the Câmera panel (the agent owns the engine). */
function GestureToggle() {
  const state = useHud((s) => s.gestures.state);
  const [busy, setBusy] = useState(false);
  const linked = state !== 'unknown';
  const running = linked && state !== 'off';

  const toggle = async () => {
    setBusy(true);
    try {
      const reply = await gestureCommand(running ? 'off' : 'on');
      useHud.getState().setGestures(liveFromReply(useHud.getState().gestures, reply));
      if (!reply.ok || reply.error) useHud.getState().addLog('error', reply.message);
    } catch (error) {
      useHud.getState().addLog('error', error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      className={`chip-btn ${running ? 'chip-btn--on' : ''}`}
      disabled={!linked || busy}
      onClick={() => void toggle()}
      title={linked ? undefined : 'Abra o link: os gestos rodam junto com o Jarvis'}
    >
      {busy ? 'Aguarde…' : running ? 'Desligar gestos' : 'Ligar gestos'}
    </button>
  );
}

/**
 * Live webcam feed (CAM-19) as one place to see yourself, the hand the gestures see and what
 * Jarvis saw. The <img> holds the MJPEG connection: closing the panel lets the camera turn off.
 */
export function CameraBody({ data }: { data: CameraData }) {
  const camera = useHud((s) => s.camera);
  const linked = useHud((s) => s.gestures.state !== 'unknown');
  const now = useClock(1000);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [seenLive, setSeenLive] = useState(false);
  const [showStill, setShowStill] = useState(false);
  const [mirrored, setMirrored] = useState(loadMirror);
  const feed = useRef<HTMLImageElement>(null);

  const active = camera?.active ?? false;
  useEffect(() => {
    if (loaded && active) setSeenLive(true);
  }, [loaded, active]);

  // Browsers keep an MJPEG request open until the image source changes: drop it explicitly.
  useEffect(() => {
    const node = feed.current;
    return () => {
      if (node) node.src = '';
    };
  }, [attempt]);

  // While this panel is open the gesture engine sends the hand it sees (gestures.py set_stream).
  useEffect(() => {
    if (!linked) return;
    gestureCommand('stream_on').catch(() => undefined);
    return () => {
      gestureCommand('stream_off').catch(() => undefined);
      useHud.getState().setHands(null);
    };
  }, [linked]);

  const status = feedStatus(camera, { loaded, failed, seenLive });
  const stopped = failed || (seenLive && !active);
  const disabled = camera !== null && !camera.enabled;

  const reconnect = () => {
    setLoaded(false);
    setFailed(false);
    setSeenLive(false);
    setAttempt((n) => n + 1);
  };
  const powerOff = async () => {
    await turnCameraOff();
    refreshCamera();
    useHud.getState().closeCards(['camera']);
    useHud.getState().addLog('info', 'Câmera desligada pelo HUD');
  };
  const toggleMirror = () => {
    saveMirror(!mirrored);
    setMirrored(!mirrored);
  };

  return (
    <figure className="cam">
      <div className={`cam__feed ${loaded && !stopped ? 'cam__feed--live' : ''} ${mirrored ? 'cam__feed--mirror' : ''}`}>
        {!disabled && (
          <img
            key={attempt}
            ref={feed}
            className="cam__live"
            src={`${CAMERA_STREAM_URL}?a=${attempt}`}
            alt="Feed ao vivo da webcam"
            onLoad={() => {
              setLoaded(true);
              refreshCamera();
            }}
            onError={() => {
              setFailed(true);
              refreshCamera();
            }}
          />
        )}
        {!showStill && loaded && !stopped && <HandOverlay feed={feed} mirrored={mirrored} />}
        {showStill && data.snapshot && <img className="cam__live cam__live--still" src={data.snapshot} alt="Quadro analisado pelo Jarvis" />}
        <div className="cam__scanlines" />
        <div className="cam__sweep" />
        <span className="cam__corner cam__corner--tl" />
        <span className="cam__corner cam__corner--tr" />
        <span className="cam__corner cam__corner--bl" />
        <span className="cam__corner cam__corner--br" />
        <Reticle />
        <div className="cam__tag cam__tag--tl">
          <i className={`cam__dot ${loaded && !stopped ? 'cam__dot--on' : ''}`} />
          {showStill ? 'Quadro analisado' : loaded && !stopped ? 'Ao vivo' : 'Sem sinal'}
        </div>
        <div className="cam__tag cam__tag--tr">{camera?.device ?? 'Webcam'}</div>
        <div className="cam__tag cam__tag--bl">{stamp.format(showStill && data.takenAt ? data.takenAt : now).replace(',', ' ·')}</div>
        <div className="cam__tag cam__tag--br">{feedSpecs(camera)}</div>
        {!showStill && loaded && !stopped && <GestureBanner />}
        {status && !showStill && (
          <div className="cam__status" role="status">
            <span>{status}</span>
            {stopped && !disabled && (
              <button type="button" className="btn btn--ghost cam__btn" onClick={reconnect}>
                Religar
              </button>
            )}
          </div>
        )}
        {data.snapshot && (
          <button
            type="button"
            className={`cam__still ${showStill ? 'cam__still--on' : ''}`}
            onClick={() => setShowStill((on) => !on)}
            title={showStill ? 'Voltar ao vivo' : 'Ver o quadro que o Jarvis analisou'}
          >
            <img src={data.snapshot} alt="" />
            <span>{showStill ? 'Ao vivo' : 'Analisado'}</span>
          </button>
        )}
      </div>
      <VisionReadouts data={data} />
      <figcaption className="cam__foot">
        <span className="card__sub">Imagem local · nada é gravado</span>
        <span className="cam__actions">
          <GestureToggle />
          <button
            type="button"
            className={`chip-btn ${mirrored ? 'chip-btn--on' : ''}`}
            onClick={toggleMirror}
            aria-pressed={mirrored}
            title="Mostrar como um espelho (o Jarvis analisa a imagem sem espelhar)"
          >
            Espelho
          </button>
          <button type="button" className="btn btn--ghost btn--danger cam__btn" onClick={() => void powerOff()}>
            Desligar câmera
          </button>
        </span>
      </figcaption>
    </figure>
  );
}
