/** SAU-40: histórico local do Jarvis (tempo de resposta, ativações, falhas) e as sugestões de ajuste. */

import { formatSeconds } from './latency';
import { wakeWordLabel } from './wake';

export const HEALTH_RANGES = [1, 7, 30] as const;
export type HealthRange = (typeof HEALTH_RANGES)[number];

export interface HealthSuggestion {
  level: 'warn' | 'info';
  area: 'wake' | 'latency' | 'tools' | 'models' | 'memory';
  text: string;
}

export interface HealthWake {
  word: string;
  threshold: number | null;
  activations: number;
  silent: number;
  near: number;
  near_best: number | null;
}

export interface HealthSummary {
  enabled: true;
  days: number;
  events: number;
  latency: {
    daily: { day: string; median: number | null; count: number }[];
    last24: number | null;
    prev24: number | null;
    count: number;
  };
  tools: { name: string; errors: number; last: string | null }[];
  models: { pauses: { model: string; reason: string; count: number }[]; switches: number };
  wake: HealthWake[];
  memory: { searches: number; empty: number; average: number | null; min_similarity: number };
  suggestions: HealthSuggestion[];
}

export type HealthResult = HealthSummary | { enabled: false };

const PAUSE_REASONS: Record<string, string> = {
  quota: 'cota',
  overloaded: 'sobrecarga',
  unavailable: 'indisponível',
  context: 'sessão cheia',
  error: 'falha de conexão',
};

export async function fetchHealth(days: HealthRange, fetcher: typeof fetch = fetch): Promise<HealthResult> {
  const response = await fetcher(`/api/health?days=${days}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`O servidor recusou o painel de saúde (${response.status}).`);
  return (await response.json()) as HealthResult;
}

export async function clearHealth(fetcher: typeof fetch = fetch): Promise<void> {
  const response = await fetcher('/api/health', { method: 'DELETE' });
  if (!response.ok) throw new Error('Só o próprio PC pode limpar o histórico.');
}

/** A wake word opened the link and the user never spoke: one false activation of that word. */
export function reportSilentWake(word: string, fetcher: typeof fetch = fetch): Promise<unknown> {
  return fetcher('/api/health/event', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'wake_silent', key: word }),
  }).catch(() => undefined);
}

/** Did a link opened by a heard word close without a single word from the user? */
export function wasSilentWake(wakeAt: number, userHeardAt: number | null): boolean {
  return userHeardAt === null || userHeardAt < wakeAt;
}

/** "2026-10-20" → "20/10". */
export function dayLabel(day: string): string {
  const [, month, date] = day.split('-');
  return month && date ? `${date}/${month}` : day;
}

/** Daily median response times for the sparkline, skipping days without turns. */
export function latencySeries(summary: HealthSummary): { values: number[]; days: string[]; counts: number[] } {
  const days = summary.latency.daily.filter((entry) => entry.median !== null);
  return {
    values: days.map((entry) => entry.median as number),
    days: days.map((entry) => entry.day),
    counts: days.map((entry) => entry.count),
  };
}

/** Response time domain from zero, with at least 3 s so a calm week does not look dramatic. */
export function latencyDomain(values: number[]): [number, number] {
  return [0, Math.max(3, Math.ceil(Math.max(0, ...values)))];
}

/** "1,4 s (ontem 1,1 s)" for the latest day; null without turns. */
export function latencyHeadline(summary: HealthSummary): string | null {
  const { last24, prev24 } = summary.latency;
  if (last24 === null) return null;
  return prev24 === null ? formatSeconds(last24) : `${formatSeconds(last24)} (ontem ${formatSeconds(prev24)})`;
}

export function wakeLine(item: HealthWake): { label: string; detail: string; alert: boolean } {
  const parts = [`${item.activations} ativações`];
  if (item.silent) parts.push(`${item.silent} sem fala`);
  if (item.near) parts.push(`${item.near} quase${item.near_best !== null ? ` (pico ${item.near_best.toFixed(2)})` : ''}`);
  const threshold = item.threshold !== null ? ` · limiar ${item.threshold.toFixed(2)}` : '';
  return { label: `${wakeWordLabel(item.word)}${threshold}`, detail: parts.join(' · '), alert: item.silent > 0 };
}

export function pauseLine(pause: { model: string; reason: string; count: number }): string {
  return `${pause.model} · ${PAUSE_REASONS[pause.reason] ?? pause.reason} · ${pause.count}x`;
}

/** Text next to the panel title: how many hints, or that nothing needs a change. */
export function healthBadge(result: HealthResult | null): string {
  if (!result) return '…';
  if (!result.enabled) return 'desligado';
  if (result.events === 0) return 'sem dados';
  const count = result.suggestions.length;
  if (count === 0) return 'calibrado';
  return count === 1 ? '1 sugestão' : `${count} sugestões`;
}
