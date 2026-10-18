import type { CameraState } from './types';

/** MJPEG feed served by the HUD server; the webcam stays on while a panel shows it. */
export const CAMERA_STREAM_URL = '/api/camera/stream';
const STATE_URL = '/api/camera/state';
const OFF_URL = '/api/camera/off';

async function readState(response: Response): Promise<CameraState | null> {
  if (!response.ok) return null;
  return (await response.json()) as CameraState;
}

/** null when the HUD server is unreachable (or predates the camera). */
export async function fetchCameraState(): Promise<CameraState | null> {
  try {
    return await readState(await fetch(STATE_URL, { cache: 'no-store' }));
  } catch {
    return null;
  }
}

/** Turns the webcam off for everything (feed, snapshots, gestures). */
export async function turnCameraOff(): Promise<CameraState | null> {
  try {
    return await readState(await fetch(OFF_URL, { method: 'POST' }));
  } catch {
    return null;
  }
}

export interface FeedProgress {
  /** The <img> got its first frame. */
  loaded: boolean;
  /** The stream request failed (503: camera busy, missing...). */
  failed: boolean;
  /** The server reported the camera on while this feed was showing. */
  seenLive: boolean;
}

/** Message over the live image, or null while the feed is fine. */
export function feedStatus(camera: CameraState | null, { loaded, failed, seenLive }: FeedProgress): string | null {
  if (camera && !camera.enabled) return 'Câmera desativada no .env (JARVIS_ENABLE_CAMERA)';
  if (failed) return camera?.error ?? 'Sem sinal da câmera';
  if (seenLive && camera && !camera.active) return camera.error ?? 'Câmera desligada';
  if (!loaded) return 'Estabelecendo link óptico…';
  return null;
}

/** "1280×720 · 30 FPS" */
export function feedSpecs(camera: CameraState | null): string {
  if (!camera?.width || !camera.height) return '— × —';
  return `${camera.width}×${camera.height} · ${Math.round(camera.fps)} FPS`;
}
