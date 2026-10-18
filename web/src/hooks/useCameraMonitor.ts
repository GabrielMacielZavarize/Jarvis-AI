import { useEffect } from 'react';
import { fetchCameraState } from '../lib/camera';
import { useHud } from '../lib/hudStore';

const POLL_MS = 1500;
const RETRY_MS = 5000;

let refreshNow: (() => void) | null = null;

/** Reads the webcam state right away (after the feed loads or the camera is turned off). */
export function refreshCamera() {
  refreshNow?.();
}

/**
 * Polls /api/camera/state so the "CÂMERA ATIVA" indicator shows whenever the webcam is on,
 * whoever turned it on (HUD feed, a snapshot for Jarvis, gesture reading).
 */
export function useCameraMonitor() {
  useEffect(() => {
    let cancelled = false;
    let latest = 0;
    let timer: number | undefined;

    const tick = async () => {
      const mine = ++latest;
      window.clearTimeout(timer);
      const state = await fetchCameraState();
      if (cancelled || mine !== latest) return;
      const hud = useHud.getState();
      const wasActive = hud.camera?.active ?? false;
      hud.setCamera(state);
      if (state && state.active !== wasActive) {
        hud.addLog(state.active ? 'warn' : 'info', state.active ? `Câmera ligada${state.device ? ` · ${state.device}` : ''}` : 'Câmera desligada');
      }
      timer = window.setTimeout(tick, state ? POLL_MS : RETRY_MS);
    };

    refreshNow = () => void tick();
    void tick();
    return () => {
      cancelled = true;
      refreshNow = null;
      window.clearTimeout(timer);
    };
  }, []);
}
