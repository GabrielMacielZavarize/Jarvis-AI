import { describe, expect, it } from 'vitest';
import type { HudCard } from './types';
import { hasPendingWork, micLabelFor, parseWakeEvent, silenceLeft } from './wake';

const NOW = 1_000_000;
const card = (partial: Pick<HudCard, 'kind' | 'data'>) => ({ id: 'c1', createdAt: NOW, ...partial }) as HudCard;

describe('parseWakeEvent', () => {
  it('reads the events sent by the server', () => {
    expect(parseWakeEvent('{"type":"wake","score":0.91}')).toEqual({ type: 'wake', score: 0.91 });
    expect(parseWakeEvent('{"type":"wake","score":1,"routine":"bom dia"}')).toEqual({ type: 'wake', score: 1, routine: 'bom dia' });
    expect(parseWakeEvent('{"type":"config","enabled":true,"silence_s":30}')).toEqual({
      type: 'config',
      enabled: true,
      silence_s: 30,
    });
  });

  it('ignores anything else', () => {
    expect(parseWakeEvent('not json')).toBeNull();
    expect(parseWakeEvent('{"type":"other"}')).toBeNull();
    expect(parseWakeEvent('null')).toBeNull();
  });
});

describe('micLabelFor', () => {
  const devices = [
    { deviceId: 'default', label: 'Padrão - Headset (Redmi Buds 6 Pro)' },
    { deviceId: 'abc', label: 'Microphone Array (Intel® Smart Sound Technology)' },
  ];

  it('sends the label of the microphone chosen in the Sistema panel', () => {
    expect(micLabelFor('abc', devices)).toBe('Microphone Array (Intel® Smart Sound Technology)');
  });

  it('leaves the Windows default to the detector', () => {
    expect(micLabelFor('default', devices)).toBeNull();
    expect(micLabelFor('communications', devices)).toBeNull();
    expect(micLabelFor('gone', devices)).toBeNull();
  });
});

describe('hasPendingWork', () => {
  it('keeps the link open for a running timer, a code to confirm or an install', () => {
    expect(hasPendingWork([card({ kind: 'timer', data: { id: 't', label: 'Café', status: 'running', ends_at: NOW + 60_000 } })], NOW)).toBe(true);
    expect(hasPendingWork([card({ kind: 'email', data: { status: 'draft', to: 'a@b.com', code: '482913' } })], NOW)).toBe(true);
    expect(hasPendingWork([card({ kind: 'install', data: { status: 'installing' } })], NOW)).toBe(true);
  });

  it('keeps the link open while a routine runs or waits for the user\'s yes', () => {
    const routine = (status: 'running' | 'confirm' | 'done' | 'partial') =>
      card({ kind: 'routine', data: { id: 'r', name: 'Boa noite', trigger: 'voz', status, started_at: NOW, steps: [] } });
    expect(hasPendingWork([routine('running')], NOW)).toBe(true);
    expect(hasPendingWork([routine('confirm')], NOW)).toBe(true);
    expect(hasPendingWork([routine('done')], NOW)).toBe(false);
    expect(hasPendingWork([routine('partial')], NOW)).toBe(false);
  });

  it('does not wait for finished work or plain panels', () => {
    expect(hasPendingWork([card({ kind: 'timer', data: { id: 't', label: 'Café', status: 'running', ends_at: NOW - 1 } })], NOW)).toBe(false);
    expect(hasPendingWork([card({ kind: 'email', data: { status: 'sent', to: 'a@b.com' } })], NOW)).toBe(false);
    expect(hasPendingWork([card({ kind: 'note', data: { title: 'Lista', content: 'pão' } })], NOW)).toBe(false);
    expect(hasPendingWork([], NOW)).toBe(false);
  });
});

describe('silenceLeft', () => {
  const base = { now: NOW, lastActivityAt: NOW - 25_000, silenceMs: 30_000, mode: 'listening' as const, pendingWork: false };

  it('counts down from the last activity while Jarvis is listening', () => {
    expect(silenceLeft(base)).toBe(5_000);
    expect(silenceLeft({ ...base, lastActivityAt: NOW - 40_000 })).toBe(0);
  });

  it('never closes while Jarvis talks, thinks, or has work pending', () => {
    expect(silenceLeft({ ...base, mode: 'speaking' })).toBeNull();
    expect(silenceLeft({ ...base, mode: 'thinking' })).toBeNull();
    expect(silenceLeft({ ...base, pendingWork: true })).toBeNull();
  });

  it('also frees the mic when the agent never answered', () => {
    expect(silenceLeft({ ...base, mode: 'connecting' })).toBe(5_000);
    expect(silenceLeft({ ...base, mode: 'error' })).toBe(5_000);
  });

  it('is off with JARVIS_WAKE_SILENCE_SECONDS=0', () => {
    expect(silenceLeft({ ...base, silenceMs: 0 })).toBeNull();
  });
});
