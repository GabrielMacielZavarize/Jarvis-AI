import { useHud } from '../lib/hudStore';

/** Always on screen while the webcam is on, whoever is using it. Click opens the live feed. */
export function CameraIndicator() {
  const camera = useHud((s) => s.camera);
  const openCamera = useHud((s) => s.openCamera);
  if (!camera?.active) return null;

  return (
    <button type="button" className="cam-alert" onClick={openCamera} title="Abrir o feed da câmera" aria-live="polite">
      <i className="cam-alert__dot" aria-hidden />
      <span className="cam-alert__label">Câmera ativa</span>
      {camera.device && <span className="cam-alert__meta">{camera.device}</span>}
    </button>
  );
}
