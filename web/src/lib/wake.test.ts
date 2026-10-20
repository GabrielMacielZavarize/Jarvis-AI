import { describe, expect, it } from 'vitest';
import type { HudCard } from './types';
import {
  hasPendingWork,
  micLabelFor,
  noticeCard,
  noticeLogLevel,
  noticeToast,
  parseWakeEvent,
  routineWakeTitle,
  silenceLeft,
  wakePersona,
  wakeWordLabel,
  wakeWordsLabel,
} from './wake';

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

  it('reads a wake opened by a proactive notice and the notices themselves (PRO-28)', () => {
    expect(parseWakeEvent('{"type":"wake","score":1,"reason":"notice"}')).toEqual({ type: 'wake', score: 1, reason: 'notice' });
    const notice = parseWakeEvent(
      '{"type":"notice","id":"a1","topic":"battery","priority":"high","title":"Bateria baixa","message":"Bateria em 18%.","route":"hud"}',
    );
    expect(notice).toMatchObject({ type: 'notice', title: 'Bateria baixa', route: 'hud' });
    expect(parseWakeEvent('{"type":"notice","title":3}')).toBeNull();
  });

  it('reads presence wakes (PRS-25)', () => {
    expect(parseWakeEvent('{"type":"wake","score":1,"reason":"presence"}')).toEqual({ type: 'wake', score: 1, reason: 'presence' });
    expect(parseWakeEvent('{"type":"config","enabled":false,"presence":true,"silence_s":30}')).toEqual({
      type: 'config',
      enabled: false,
      presence: true,
      silence_s: 30,
    });
  });

  it('reads a routine fired by a context trigger (ROT-24)', () => {
    expect(parseWakeEvent('{"type":"wake","score":1,"reason":"context","routine":"modo foco"}')).toEqual({
      type: 'wake',
      score: 1,
      reason: 'context',
      routine: 'modo foco',
    });
    expect(routineWakeTitle('context')).toBe('Rotina por contexto');
    expect(routineWakeTitle()).toBe('Rotina agendada');
  });

  it('reads the word heard and the persona it called', () => {
    expect(parseWakeEvent('{"type":"wake","score":0.84,"word":"friday","persona":"friday"}')).toEqual({
      type: 'wake',
      score: 0.84,
      word: 'friday',
      persona: 'friday',
    });
    expect(parseWakeEvent('{"type":"status","detector":true,"listening":true,"words":["jarvis","friday"]}')).toMatchObject({
      words: ['jarvis', 'friday'],
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

describe('noticeCard', () => {
  const base = { type: 'notice', id: 'n', topic: 'battery', title: 'Bateria baixa', message: 'Bateria em 18%.' } as const;

  it('shows the notice as a panel, saying when it stayed silent', () => {
    expect(noticeCard({ ...base, priority: 'high', route: 'speak' })).toEqual({ title: 'Aviso · Bateria baixa', content: 'Bateria em 18%.' });
    expect(noticeCard({ ...base, priority: 'high', route: 'hud' }).title).toBe('Aviso · Bateria baixa · sem voz');
    expect(noticeCard({ ...base, priority: 'low', route: 'hud' }).title).toBe('Aviso · Bateria baixa');
  });

  it('highlights the important ones in the activity log', () => {
    expect(noticeLogLevel('critical')).toBe('warn');
    expect(noticeLogLevel('high')).toBe('warn');
    expect(noticeLogLevel('normal')).toBe('info');
  });
});

describe('noticeToast', () => {
  const notice = { type: 'notice' as const, id: 'n1', topic: 'battery', title: 'Bateria', message: '15% restantes', route: 'hud' as const };

  it('keeps critical notices until clicked and warns on high ones', () => {
    expect(noticeToast({ ...notice, priority: 'critical' })).toEqual({ level: 'critical', title: 'Bateria', message: '15% restantes', code: 'PRO-28' });
    expect(noticeToast({ ...notice, priority: 'high' }).level).toBe('warn');
    expect(noticeToast({ ...notice, priority: 'low' }).level).toBe('info');
  });
});

describe('wake words', () => {
  it('names what the detector heard and what it waits for', () => {
    expect(wakeWordLabel('friday')).toBe('Friday');
    expect(wakeWordLabel(undefined)).toBe('Jarvis');
    expect(wakeWordsLabel(['jarvis', 'friday'])).toBe('“Jarvis” ou “Friday”');
    expect(wakeWordsLabel([])).toBe('“Jarvis”');
  });

  it('switches the theme only to a known persona that is not on screen', () => {
    expect(wakePersona('friday', 'jarvis')).toBe('friday');
    expect(wakePersona('jarvis', 'friday')).toBe('jarvis');
    expect(wakePersona('friday', 'friday')).toBeNull();
    expect(wakePersona(undefined, 'mark3')).toBeNull();
    expect(wakePersona('ultron', 'jarvis')).toBeNull();
  });
});
