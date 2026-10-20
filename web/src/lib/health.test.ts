import { describe, expect, it, vi } from 'vitest';
import {
  clearHealth,
  dayLabel,
  fetchHealth,
  healthBadge,
  type HealthSummary,
  latencyDomain,
  latencyHeadline,
  latencySeries,
  pauseLine,
  reportSilentWake,
  wakeLine,
  wasSilentWake,
} from './health';

function summary(overrides: Partial<HealthSummary> = {}): HealthSummary {
  return {
    enabled: true,
    days: 7,
    events: 12,
    latency: {
      daily: [
        { day: '2026-10-18', median: 1.1, count: 4 },
        { day: '2026-10-19', median: null, count: 0 },
        { day: '2026-10-20', median: 1.82, count: 6 },
      ],
      last24: 1.82,
      prev24: 1.1,
      count: 10,
    },
    tools: [],
    models: { pauses: [], switches: 0 },
    wake: [],
    memory: { searches: 0, empty: 0, average: null, min_similarity: 0.6 },
    suggestions: [],
    ...overrides,
  };
}

const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

describe('health panel (SAU-40)', () => {
  it('reads the chosen window and clears the history', async () => {
    const fetcher = vi.fn(() => ok({ enabled: false }));
    await expect(fetchHealth(30, fetcher as unknown as typeof fetch)).resolves.toEqual({ enabled: false });
    expect(fetcher).toHaveBeenCalledWith('/api/health?days=30', { cache: 'no-store' });

    const refused = vi.fn(() => Promise.resolve(new Response('{}', { status: 403 })));
    await expect(clearHealth(refused as unknown as typeof fetch)).rejects.toThrow('Só o próprio PC');
    await expect(fetchHealth(7, refused as unknown as typeof fetch)).rejects.toThrow('403');
  });

  it('reports a wake that opened a link nobody spoke in', async () => {
    const fetcher = vi.fn(() => ok({ ok: true }));
    await reportSilentWake('friday', fetcher as unknown as typeof fetch);
    expect(fetcher).toHaveBeenCalledWith('/api/health/event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'wake_silent', key: 'friday' }),
    });
    const down = vi.fn(() => Promise.reject(new Error('offline')));
    await expect(reportSilentWake('jarvis', down as unknown as typeof fetch)).resolves.toBeUndefined();

    expect(wasSilentWake(1000, null)).toBe(true);
    expect(wasSilentWake(1000, 900)).toBe(true);
    expect(wasSilentWake(1000, 1500)).toBe(false);
  });

  it('turns the daily medians into a chart, skipping days without turns', () => {
    const series = latencySeries(summary());
    expect(series).toEqual({ values: [1.1, 1.82], days: ['2026-10-18', '2026-10-20'], counts: [4, 6] });
    expect(dayLabel('2026-10-20')).toBe('20/10');
    expect(latencyDomain(series.values)).toEqual([0, 3]);
    expect(latencyDomain([4.2])).toEqual([0, 5]);
    expect(latencyHeadline(summary())).toBe('1,8 s (ontem 1,1 s)');
    expect(latencyHeadline(summary({ latency: { daily: [], last24: null, prev24: null, count: 0 } }))).toBeNull();
  });

  it('describes wake words and model pauses', () => {
    expect(wakeLine({ word: 'friday', threshold: 0.7, activations: 5, silent: 4, near: 2, near_best: 0.61 })).toEqual({
      label: 'Friday · limiar 0.70',
      detail: '5 ativações · 4 sem fala · 2 quase (pico 0.61)',
      alert: true,
    });
    expect(wakeLine({ word: 'jarvis', threshold: null, activations: 2, silent: 0, near: 0, near_best: null })).toEqual({
      label: 'Jarvis',
      detail: '2 ativações',
      alert: false,
    });
    expect(pauseLine({ model: 'gemini-live', reason: 'quota', count: 3 })).toBe('gemini-live · cota · 3x');
  });

  it('badges the panel title', () => {
    expect(healthBadge(null)).toBe('…');
    expect(healthBadge({ enabled: false })).toBe('desligado');
    expect(healthBadge(summary({ events: 0 }))).toBe('sem dados');
    expect(healthBadge(summary())).toBe('calibrado');
    const hint = { level: 'warn' as const, area: 'wake' as const, text: 'suba' };
    expect(healthBadge(summary({ suggestions: [hint] }))).toBe('1 sugestão');
    expect(healthBadge(summary({ suggestions: [hint, { ...hint, text: 'outra' }] }))).toBe('2 sugestões');
  });
});
