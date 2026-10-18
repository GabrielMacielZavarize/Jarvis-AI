import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { savedDate } from './format';
import { useHud } from './hudStore';
import { forgetMemory, MemoryOfflineError, parseMemoryReply, setMemoryTransport } from './memoryLink';
import { matchPanels, panelDetail } from './panels';
import type { HudCard, MemoryData } from './types';

const memories: MemoryData = {
  status: 'list',
  total: 3,
  items: [
    { id: 'a1', fact: 'Prefere lo-fi para programar', category: 'preferencia', created_at: '2026-10-18T10:31:00-03:00' },
    { id: 'b2', fact: 'Reunião de segunda-feira às 9h', category: 'agenda', created_at: '2026-10-17T09:00:00-03:00' },
    { id: 'c3', fact: 'Mora em Criciúma', category: 'perfil', created_at: '2026-10-16T08:00:00-03:00' },
  ],
};

beforeEach(() => {
  useHud.setState({ cards: [], expandedId: null });
});

afterEach(() => {
  setMemoryTransport(null);
  useHud.setState({ demo: false, cards: [], expandedId: null });
});

describe('forgetMemory', () => {
  it('asks the agent over RPC to forget only that id and returns the new list', async () => {
    const transport = vi.fn(async (payload: string) => {
      expect(JSON.parse(payload)).toEqual({ action: 'forget', id: 'b2' });
      return JSON.stringify({ ok: true, status: 'forgotten', items: [memories.items[0], memories.items[2]], total: 2, message: 'Esquecido: Reunião' });
    });
    setMemoryTransport(transport);

    const reply = await forgetMemory(memories, 'b2');

    expect(transport).toHaveBeenCalledOnce();
    expect(reply.ok).toBe(true);
    expect(reply.items.map((item) => item.id)).toEqual(['a1', 'c3']);
    expect(reply.total).toBe(2);
  });

  it('keeps a filtered panel filtered after the delete', async () => {
    setMemoryTransport(async () =>
      JSON.stringify({ ok: true, status: 'forgotten', items: [memories.items[0], memories.items[2]], total: 2 }),
    );
    const filtered: MemoryData = { ...memories, query: 'agenda lo-fi', items: memories.items.slice(0, 2) };

    const reply = await forgetMemory(filtered, 'b2');

    expect(reply.query).toBe('agenda lo-fi');
    expect(reply.items.map((item) => item.id)).toEqual(['a1']);
  });

  it('fails clearly without a link to the agent', async () => {
    await expect(forgetMemory(memories, 'a1')).rejects.toBeInstanceOf(MemoryOfflineError);
  });

  it('drops the item locally in demo mode', async () => {
    useHud.setState({ demo: true });
    const reply = await forgetMemory(memories, 'a1');
    expect(reply.ok).toBe(true);
    expect(reply.items.map((item) => item.id)).toEqual(['b2', 'c3']);
    expect(reply.message).toContain('lo-fi');
  });
});

describe('parseMemoryReply', () => {
  it('ignores malformed items', () => {
    const reply = parseMemoryReply(JSON.stringify({ ok: true, items: [{ id: 'x', fact: 'ok', category: 'outro' }, { id: 3 }, null] }));
    expect(reply.items).toHaveLength(1);
    expect(reply.total).toBe(1);
    expect(reply.status).toBe('list');
  });
});

describe('memory panel', () => {
  it('shows the count and the query as its subtitle', () => {
    const card = { id: 'm', kind: 'memory', data: { ...memories, query: 'música' }, createdAt: 1 } as HudCard;
    expect(panelDetail(card)).toBe('"música" · 3 memórias');
  });

  it('"aba da memória" is the memory panel, not the diagnostics one', () => {
    useHud.getState().pushCard('diagnostics', {
      hostname: 'MARK-L',
      os: 'Windows 11',
      cpu: { percent: 10, cores: 8, per_core: [] },
      memory: { percent: 40, used_gb: 6, total_gb: 16 },
      disk: { mount: 'C:\\', percent: 50, used_gb: 200, total_gb: 400 },
      uptime_s: 100,
      processes: 200,
    });
    useHud.getState().pushCard('memory', memories);
    const { matched } = matchPanels(useHud.getState().cards, ['memória']);
    expect(matched.map((card) => card.kind)).toEqual(['memory']);
  });

  it('updateCard swaps the data without moving the panel', () => {
    useHud.getState().pushCard('memory', memories);
    useHud.getState().pushCard('note', { title: 'Nota', content: 'x' });
    const id = useHud.getState().cards.find((card) => card.kind === 'memory')!.id;

    useHud.getState().updateCard(id, 'memory', { ...memories, status: 'forgotten', items: [], total: 0 });

    const cards = useHud.getState().cards;
    expect(cards.map((card) => card.kind)).toEqual(['note', 'memory']);
    expect(cards[1].kind === 'memory' && cards[1].data.total).toBe(0);
  });
});

describe('savedDate', () => {
  it('formats the saved day without shifting the timezone', () => {
    expect(savedDate('2026-10-18T23:59:00-03:00')).toBe('18/10/2026');
    expect(savedDate('')).toBe('');
  });
});
