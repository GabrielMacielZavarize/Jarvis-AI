/**
 * Câmera panel (CAM-19) as one place to see yourself, the hand the gesture engine sees and what
 * Jarvis saw of you. The hands come from gestures.py (GestureEngine._stream_hands) about 12 times
 * a second while the panel is open; the presence and the last analysed frame come from elsewhere.
 */
import type { ChatLine, GestureEvent, GestureState, HandsEvent } from './types';

/** What the panel draws over the live feed. */
export interface HandFrame {
  /** One array per hand: x0, y0, x1, y1... in 0-1 of the mirrored frame (selfie view). */
  hands: number[][];
  pose: string;
  state: GestureState;
  /** What the engine says right now ("→ MONITOR DE CIMA"), as on the desktop overlay. */
  title: string | null;
  detail: string | null;
  progress: number | null;
  tone: string | null;
  fps: number;
  /** When the HUD got it (ms). */
  at: number;
}

/** A hand drawing older than this is gone (lost frames, gestures turned off). */
export const HAND_STALE_MS = 1500;

const STATES = new Set<GestureState>(['idle', 'armed', 'grab', 'close', 'mouse']);

export function handFrameFrom(event: HandsEvent, now: number): HandFrame {
  const hands = Array.isArray(event.hands)
    ? event.hands.filter((hand) => Array.isArray(hand) && hand.length === 42 && hand.every((value) => Number.isFinite(value)))
    : [];
  return {
    hands,
    pose: typeof event.pose === 'string' ? event.pose : 'none',
    state: STATES.has(event.state as GestureState) ? (event.state as GestureState) : 'idle',
    title: event.title ?? null,
    detail: event.detail ?? null,
    progress: typeof event.progress === 'number' ? Math.max(0, Math.min(1, event.progress)) : null,
    tone: event.tone ?? null,
    fps: typeof event.fps === 'number' ? event.fps : 0,
    at: now,
  };
}

export function isStale(frame: HandFrame | null, now: number): boolean {
  return frame === null || now - frame.at > HAND_STALE_MS;
}

/** True for the engine's first state after starting: the HUD opens the Câmera panel then. */
export function gesturesTurnedOn(before: GestureState, event: GestureEvent): boolean {
  return event.event === 'state' && event.state !== 'off' && (before === 'off' || before === 'unknown');
}

/** Names of the engine's poses (gesture_engine.Pose), as the panel labels the hand. */
export const POSE_LABELS: Record<string, { glyph: string; name: string }> = {
  open: { glyph: '✋', name: 'Mão aberta' },
  fist: { glyph: '✊', name: 'Punho' },
  point: { glyph: '☝️', name: 'Apontando' },
  two: { glyph: '✌️', name: 'Dois dedos' },
  three: { glyph: '🤟', name: 'Três dedos' },
  pinch: { glyph: '🤏', name: 'Pinça' },
  thumb_up: { glyph: '👍', name: 'Joinha' },
  thumb_down: { glyph: '👎', name: 'Polegar para baixo' },
  rock: { glyph: '🤘', name: 'Rock' },
};

export function poseLabel(pose: string): { glyph: string; name: string } | null {
  return POSE_LABELS[pose] ?? null;
}

/** MediaPipe's 21 hand points: the bones to draw (gestures.HAND_CONNECTIONS). */
export const HAND_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];

/** Where the image sits in its box with object-fit: cover (offset and scale in CSS pixels). */
export interface CoverMap {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function coverMap(boxWidth: number, boxHeight: number, imageWidth: number, imageHeight: number): CoverMap {
  if (!imageWidth || !imageHeight) return { x: 0, y: 0, width: boxWidth, height: boxHeight };
  const scale = Math.max(boxWidth / imageWidth, boxHeight / imageHeight);
  const width = imageWidth * scale;
  const height = imageHeight * scale;
  return { x: (boxWidth - width) / 2, y: (boxHeight - height) / 2, width, height };
}

/**
 * The points of one hand in the panel's pixels. The engine reports the mirrored frame; with the
 * feed shown as the camera sees it (not mirrored), x flips back.
 */
export function handPixels(hand: number[], map: CoverMap, mirrored: boolean): [number, number][] {
  const points: [number, number][] = [];
  for (let i = 0; i + 1 < hand.length; i += 2) {
    const x = mirrored ? hand[i] : 1 - hand[i];
    points.push([map.x + x * map.width, map.y + hand[i + 1] * map.height]);
  }
  return points;
}

/** Color of the hand drawing for each engine state (CSS custom properties of the theme). */
export const STATE_TONES: Record<GestureState, string> = {
  unknown: '--text-faint',
  off: '--text-faint',
  idle: '--text-dim',
  armed: '--c-primary',
  grab: '--c-accent',
  close: '--c-danger',
  mouse: '--c-ok',
};

/** Longest a reply can wait after the photo and still be the answer about it. */
const ANSWER_WINDOW_MS = 60_000;

/**
 * What Jarvis said about the frame it analysed: the first thing it said after the photo.
 * null while it has not answered (or when the conversation moved on without an answer).
 */
export function cameraAnswer(lines: ChatLine[], takenAt: number | null | undefined): string | null {
  if (!takenAt) return null;
  // The tool reports the photo a moment before it reaches the HUD: a little slack.
  const reply = lines.find((line) => line.role === 'agent' && line.ts >= takenAt - 2000 && line.ts - takenAt <= ANSWER_WINDOW_MS);
  return reply?.text.trim() || null;
}

const MIRROR_KEY = 'jarvis.camera.mirror';

/** The live feed as a mirror (default: you move right, the image moves right). */
export function loadMirror(): boolean {
  try {
    return window.localStorage.getItem(MIRROR_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function saveMirror(on: boolean) {
  try {
    window.localStorage.setItem(MIRROR_KEY, on ? 'on' : 'off');
  } catch {
    // Private windows may refuse storage; the toggle still works for this visit.
  }
}
