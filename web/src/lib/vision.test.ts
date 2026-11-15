import { describe, expect, it } from 'vitest';
import { reduceGesture, INITIAL_GESTURES } from './gestures';
import type { ChatLine, HandsEvent } from './types';
import {
  cameraAnswer,
  coverMap,
  gesturesTurnedOn,
  HAND_CONNECTIONS,
  HAND_STALE_MS,
  handFrameFrom,
  handPixels,
  isStale,
  poseLabel,
} from './vision';

const hand = Array.from({ length: 42 }, (_, index) => (index % 2 === 0 ? 0.25 : 0.5));
const event = (extra: Partial<HandsEvent> = {}): HandsEvent => ({
  type: 'gesture',
  event: 'hands',
  hands: [hand],
  pose: 'fist',
  state: 'grab',
  title: '→ MONITOR DE CIMA',
  detail: 'abra a mão para soltar',
  progress: null,
  tone: 'armed',
  fps: 24,
  ts: 1,
  ...extra,
});

describe('hand frames from the gesture engine', () => {
  it('keeps the valid hands and the engine text', () => {
    const frame = handFrameFrom(event({ hands: [hand, [0.1, 0.2], [Number.NaN, ...hand.slice(1)]] }), 1000);
    expect(frame.hands).toEqual([hand]);
    expect(frame).toMatchObject({ pose: 'fist', state: 'grab', title: '→ MONITOR DE CIMA', fps: 24, at: 1000 });
    expect(handFrameFrom(event({ state: 'warp', progress: 3 }), 0)).toMatchObject({ state: 'idle', progress: 1 });
  });

  it('goes stale when frames stop coming', () => {
    const frame = handFrameFrom(event(), 1000);
    expect(isStale(frame, 1000 + HAND_STALE_MS - 1)).toBe(false);
    expect(isStale(frame, 1000 + HAND_STALE_MS + 1)).toBe(true);
    expect(isStale(null, 0)).toBe(true);
  });

  it('does not touch the Gestos panel summary', () => {
    expect(reduceGesture(INITIAL_GESTURES, event(), 0)).toBe(INITIAL_GESTURES);
  });

  it('names the poses and draws the 21 points', () => {
    expect(poseLabel('fist')?.name).toBe('Punho');
    expect(poseLabel('none')).toBeNull();
    expect(Math.max(...HAND_CONNECTIONS.flat())).toBe(20);
  });
});

describe('drawing over the feed', () => {
  it('maps object-fit: cover', () => {
    expect(coverMap(320, 180, 1280, 720)).toEqual({ x: 0, y: 0, width: 320, height: 180 });
    // A 4:3 webcam in a 16:9 box: wider than the box, cropped top and bottom.
    const map = coverMap(320, 180, 640, 480);
    expect(map.width).toBe(320);
    expect(map.height).toBeCloseTo(240);
    expect(map.y).toBeCloseTo(-30);
  });

  it('flips x back when the feed is not a mirror', () => {
    const map = coverMap(200, 100, 200, 100);
    expect(handPixels(hand, map, true)[0]).toEqual([50, 50]);
    expect(handPixels(hand, map, false)[0]).toEqual([150, 50]);
    expect(handPixels(hand, map, true)).toHaveLength(21);
  });
});

describe('what Jarvis said about the photo', () => {
  const lines: ChatLine[] = [
    { id: '1', role: 'user', text: 'O que você está vendo?', ts: 9_000 },
    { id: '2', role: 'agent', text: 'Um caderno azul na sua mão.', ts: 12_000 },
    { id: '3', role: 'agent', text: 'Mais alguma coisa?', ts: 14_000 },
  ];

  it('is the first reply after the photo', () => {
    expect(cameraAnswer(lines, 10_500)).toBe('Um caderno azul na sua mão.');
  });

  it('is nothing before he answers or without a photo', () => {
    expect(cameraAnswer(lines.slice(0, 1), 10_500)).toBeNull();
    expect(cameraAnswer(lines, null)).toBeNull();
    expect(cameraAnswer(lines, 200_000)).toBeNull();
  });
});

describe('opening the Câmera panel', () => {
  it('opens when the gestures start, not on every state', () => {
    const armed = { type: 'gesture', event: 'state', state: 'armed', ts: 1 } as const;
    expect(gesturesTurnedOn('off', armed)).toBe(true);
    expect(gesturesTurnedOn('unknown', armed)).toBe(true);
    expect(gesturesTurnedOn('idle', armed)).toBe(false);
    expect(gesturesTurnedOn('off', { ...armed, state: 'off' })).toBe(false);
    expect(gesturesTurnedOn('off', event())).toBe(false);
  });
});
