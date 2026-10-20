import { afterEach, describe, expect, it } from 'vitest';
import {
  agoLabel,
  editorValue,
  gestureCommand,
  INITIAL_GESTURES,
  liveFromReply,
  parseGestureReply,
  plainName,
  reduceGesture,
  setGestureTransport,
} from './gestures';
import type { CustomGesture, GestureEvent, GestureLive } from './types';

/** One event without the envelope, keeping each variant's own fields. */
type Body = GestureEvent extends infer E ? (E extends GestureEvent ? Omit<E, 'ts' | 'type'> : never) : never;

const play = (events: Body[]): GestureLive =>
  events.reduce<GestureLive>(
    (live, event, index) => reduceGesture(live, { type: 'gesture', ts: index, ...event } as GestureEvent, 1000 + index),
    INITIAL_GESTURES,
  );

describe('reduceGesture', () => {
  it('follows a throw: armed, grab, aim and the result', () => {
    const live = play([
      { event: 'state', state: 'armed' },
      { event: 'grab', title: 'Chrome' },
      { event: 'aim', direction: 'up', target: 'monitor de cima' },
    ]);
    expect(live).toMatchObject({ state: 'grab', holding: 'Chrome', aim: 'monitor de cima' });
    const done = reduceGesture(live, { type: 'gesture', event: 'action', action: 'throw', ok: true, message: 'Chrome → monitor de cima', ts: 9 }, 5000);
    expect(done).toMatchObject({ state: 'armed', holding: null, aim: null, last: { text: 'Chrome → monitor de cima', ok: true, at: 5000 } });
  });

  it('a cancel lets go of the window, and turning off closes the panel', () => {
    expect(play([{ event: 'grab', title: 'Notion' }, { event: 'cancel' }])).toMatchObject({ state: 'armed', holding: null });
    expect(play([{ event: 'panel', visible: true }]).panel).toBe(true);
    expect(play([{ event: 'panel', visible: true }, { event: 'state', state: 'off' }]).panel).toBe(false);
  });

  it('keeps failures apart from successes', () => {
    const live = play([{ event: 'action', action: 'ok', ok: false, message: 'Nenhuma mídia tocando' }]);
    expect(live.last).toMatchObject({ ok: false, text: 'Nenhuma mídia tocando' });
  });
});

describe('the panel RPC', () => {
  afterEach(() => setGestureTransport(null));

  it('refuses without a link and reads the agent reply', async () => {
    await expect(gestureCommand('on')).rejects.toThrow('Sem link');
    let sent = '';
    setGestureTransport(async (payload) => {
      sent = payload;
      return JSON.stringify({ ok: true, message: 'Gestos ligados', running: true, state: 'armed', panel: true, fps: 29 });
    });
    const reply = await gestureCommand('on');
    expect(JSON.parse(sent)).toEqual({ action: 'on' });
    expect(reply).toMatchObject({ ok: true, running: true, state: 'armed', panel: true, fps: 29, error: null });
    expect(liveFromReply(INITIAL_GESTURES, reply)).toMatchObject({ state: 'armed', panel: true });
  });

  it('treats a stopped service and odd replies as off', () => {
    const reply = parseGestureReply(JSON.stringify({ ok: true, running: false, state: 'armed', error: 'webcam ocupada' }));
    expect(liveFromReply(INITIAL_GESTURES, reply).state).toBe('off');
    expect(parseGestureReply('{"state": "voando"}').state).toBe('off');
  });
});

describe('editor helpers', () => {
  it('opens each binding with its kind and value', () => {
    expect(editorValue({ tipo: 'acao', acao: 'play_pause' })).toEqual({ kind: 'action', value: 'play_pause' });
    expect(editorValue({ tipo: 'app', nome: 'spotify' })).toEqual({ kind: 'app', value: 'spotify' });
    expect(editorValue({ tipo: 'atalho', teclas: 'Ctrl+Shift+M' })).toEqual({ kind: 'keys', value: 'Ctrl+Shift+M' });
    expect(editorValue({ tipo: 'nada' })).toEqual({ kind: 'none', value: '' });
  });

  it('names and times', () => {
    expect(plainName({ name: 'OK (👌)' } as CustomGesture)).toBe('OK');
    expect(plainName({ name: 'pinça subindo' } as CustomGesture)).toBe('pinça subindo');
    expect(agoLabel(0, 1000)).toBe('agora');
    expect(agoLabel(0, 12_000)).toBe('há 12 s');
    expect(agoLabel(0, 180_000)).toBe('há 3 min');
  });
});
