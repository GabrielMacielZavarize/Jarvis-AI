import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { diaryClock, diaryDayLabel, diaryDetail, diaryMatchLabel, DiaryOfflineError, forgetDiary, groupByDay, parseDiaryReply, setDiaryTransport } from './diaryLink';
import { useHud } from './hudStore';
import { matchPanels, panelDetail, PANEL_META } from './panels';
import { toolCode, TOOL_LABELS } from './catalog';
import type { DiaryData, HudCard } from './types';

const diary: DiaryData = {
  status: 'list',
  total: 3,
  items: [
    { id: 'a1', date: '2026-10-19', started_at: '2026-10-19T21:10:00-03:00', title: 'Bug do login no Jarvis-AI', asked: ['Ajuda com o bug'], decided: [], pending: ['Escrever os testes'] },
    { id: 'b2', date: '2026-10-19', started_at: '2026-10-19T08:30:00-03:00', title: 'Viagem para Criciúma', asked: ['Clima no sábado'], decided: ['Vai chover'], pending: [] },
    { id: 'c3', date: '2026-10-16', started_at: '2026-10-16T10:00:00-03:00', title: 'Playlist de lo-fi', asked: [], decided: ['Tocou lo-fi'], pending: [] },
  ],
};

beforeEach(() => {
  useHud.setState({ cards: [], expandedId: null });
});

afterEach(() => {
  setDiaryTransport(null);
  useHud.setState({ demo: false, cards: [], expandedId: null });
});

describe('forgetDiary', () => {
  it('asks the agent over RPC to delete only that id', async () => {
    const transport = vi.fn(async (payload: string) => {
      expect(JSON.parse(payload)).toEqual({ action: 'forget', id: 'b2' });
      return JSON.stringify({ ok: true, status: 'forgotten', items: [diary.items[0], diary.items[2]], total: 2, message: 'Apagada: Viagem' });
    });
    setDiaryTransport(transport);

    const reply = await forgetDiary(diary, 'b2');

    expect(transport).toHaveBeenCalledOnce();
    expect(reply.ok).toBe(true);
    expect(reply.items.map((item) => item.id)).toEqual(['a1', 'c3']);
  });

  it('keeps a filtered panel filtered after the delete', async () => {
    setDiaryTransport(async () => JSON.stringify({ ok: true, status: 'forgotten', items: [diary.items[2]], total: 2 }));

    const reply = await forgetDiary({ ...diary, period: 'ontem (19/10)', items: diary.items.slice(0, 2) }, 'b2');

    expect(reply.period).toBe('ontem (19/10)');
    expect(reply.items.map((item) => item.id)).toEqual(['a1']);
  });

  it('fails without a link, except in the demo', async () => {
    await expect(forgetDiary(diary, 'a1')).rejects.toBeInstanceOf(DiaryOfflineError);

    useHud.setState({ demo: true });
    const reply = await forgetDiary(diary, 'a1');
    expect(reply.ok).toBe(true);
    expect(reply.total).toBe(2);
    expect(reply.message).toBe('Apagada: Bug do login no Jarvis-AI');
  });
});

describe('parseDiaryReply', () => {
  it('drops malformed entries and fills the lists', () => {
    const reply = parseDiaryReply(JSON.stringify({ ok: true, items: [{ id: 'x', date: '2026-10-19', title: 'Ok', asked: ['a', 3] }, { id: 'y' }] }));
    expect(reply.items).toHaveLength(1);
    expect(reply.items[0]).toMatchObject({ asked: ['a'], decided: [], pending: [], started_at: '' });
    expect(reply.total).toBe(1);
  });
});

describe('labels', () => {
  const today = new Date(2026, 9, 20, 15, 0);

  it('names the day like people say it', () => {
    expect(diaryDayLabel('2026-10-20', today)).toBe('hoje, 20/10');
    expect(diaryDayLabel('2026-10-19', today)).toBe('ontem, 19/10');
    expect(diaryDayLabel('2026-10-16', today)).toBe('sexta, 16/10');
    expect(diaryClock('2026-10-19T21:10:00-03:00')).toBe('21:10');
    expect(diaryMatchLabel({ match: 'meaning', score: 0.82 })).toBe('pelo sentido · 82%');
  });

  it('groups by day keeping the order', () => {
    expect(groupByDay(diary.items).map((group) => [group.date, group.items.length])).toEqual([
      ['2026-10-19', 2],
      ['2026-10-16', 1],
    ]);
  });

  it('describes and finds the panel', () => {
    const card: HudCard = { id: 'card-1', kind: 'diary', data: { ...diary, period: 'ontem (19/10)' }, createdAt: 1 };
    expect(diaryDetail(diary)).toBe('3 conversas');
    expect(panelDetail(card)).toBe('ontem (19/10) · 3 conversas');
    expect(PANEL_META.diary.code).toBe('DIA-36');
    expect(matchPanels([card], ['diário']).matched.map((match) => match.id)).toEqual(['card-1']);
    expect(toolCode('diary_lookup')).toBe('DIA-36');
    expect(toolCode('forget_diary')).toBe('DIA-36');
    expect(TOOL_LABELS.diary_lookup).toBeTruthy();
  });
});
