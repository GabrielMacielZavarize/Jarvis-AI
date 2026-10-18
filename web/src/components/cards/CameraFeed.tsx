import { useEffect, useRef, useState } from 'react';
import { useClock } from '../../hooks/useClock';
import { refreshCamera } from '../../hooks/useCameraMonitor';
import { CAMERA_STREAM_URL, feedSpecs, feedStatus, turnCameraOff } from '../../lib/camera';
import { useHud } from '../../lib/hudStore';
import type { CameraData } from '../../lib/types';

const stamp = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

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

/** Live webcam feed (CAM-19). The <img> holds the MJPEG connection: closing the panel lets the camera turn off. */
export function CameraBody({ data }: { data: CameraData }) {
  const camera = useHud((s) => s.camera);
  const now = useClock(1000);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [seenLive, setSeenLive] = useState(false);
  const [showStill, setShowStill] = useState(false);
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

  return (
    <figure className="cam">
      <div className={`cam__feed ${loaded && !stopped ? 'cam__feed--live' : ''}`}>
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
      <figcaption className="cam__foot">
        <span className="card__sub">
          {data.question ? `“${data.question}”` : 'Imagem local · nada é gravado'}
        </span>
        <button type="button" className="btn btn--ghost btn--danger cam__btn" onClick={() => void powerOff()}>
          Desligar câmera
        </button>
      </figcaption>
    </figure>
  );
}
