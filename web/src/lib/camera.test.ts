import { beforeEach, describe, expect, it } from 'vitest';
import { feedSpecs, feedStatus } from './camera';
import { useHud } from './hudStore';
import type { CameraState } from './types';

const on: CameraState = {
  enabled: true,
  active: true,
  streaming: true,
  users: 1,
  pinned: false,
  device: 'ASUS FHD webcam',
  backend: 'MSMF',
  width: 1280,
  height: 720,
  fps: 30.4,
  since: 1,
  error: null,
};
const off: CameraState = { ...on, active: false, streaming: false, users: 0, width: null, height: null, fps: 0, since: null };

describe('camera feed status', () => {
  it('shows nothing over a healthy live feed', () => {
    expect(feedStatus(on, { loaded: true, failed: false, seenLive: true })).toBeNull();
    expect(feedSpecs(on)).toBe('1280×720 · 30 FPS');
  });

  it('waits for the first frame without claiming the camera is off', () => {
    expect(feedStatus(off, { loaded: false, failed: false, seenLive: false })).toBe('Estabelecendo link óptico…');
    // Loaded before the next state poll: not "desligada" yet.
    expect(feedStatus(off, { loaded: true, failed: false, seenLive: false })).toBeNull();
  });

  it('says when the camera was turned off or failed', () => {
    expect(feedStatus(off, { loaded: true, failed: false, seenLive: true })).toBe('Câmera desligada');
    expect(feedStatus({ ...off, error: 'A webcam está em uso.' }, { loaded: false, failed: true, seenLive: false })).toBe(
      'A webcam está em uso.',
    );
    expect(feedStatus(null, { loaded: false, failed: true, seenLive: false })).toBe('Sem sinal da câmera');
    expect(feedStatus({ ...off, enabled: false }, { loaded: false, failed: false, seenLive: false })).toMatch('JARVIS_ENABLE_CAMERA');
    expect(feedSpecs(off)).toBe('— × —');
  });
});

describe('camera panel', () => {
  beforeEach(() => useHud.setState({ cards: [], expandedId: null }));

  it('stays on screen while other panels pile up', () => {
    const hud = useHud.getState();
    hud.pushCard('camera', {});
    for (let index = 0; index < 5; index++) hud.pushCard('note', { title: `Nota ${index}`, content: '' });
    expect(useHud.getState().cards.map((card) => card.kind)).toContain('camera');
  });

  it('opening it again keeps the frame Jarvis analysed', () => {
    useHud.getState().pushCard('camera', { snapshot: 'blob:1', takenAt: 5, question: 'que livro é esse?' });
    useHud.getState().openCamera();
    const cards = useHud.getState().cards;
    expect(cards).toHaveLength(1);
    expect(cards[0].kind === 'camera' && cards[0].data.snapshot).toBe('blob:1');
  });

  it('can be closed by voice as "câmera" or "webcam"', () => {
    useHud.getState().openCamera();
    const listed = useHud.getState().runPanelCommand('list', []);
    expect(listed.open[0]).toMatchObject({ kind: 'camera', title: 'Câmera', detail: 'ao vivo' });
    expect(useHud.getState().runPanelCommand('close', ['webcam']).changed).toHaveLength(1);
    useHud.getState().openCamera();
    expect(useHud.getState().runPanelCommand('close', ['câmera']).changed).toHaveLength(1);
    expect(useHud.getState().cards).toEqual([]);
  });
});
