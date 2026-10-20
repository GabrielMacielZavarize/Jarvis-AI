import { useHud } from './hudStore';
import type { DiaryData, DiaryEntry } from './types';

/**
 * The Diário panel (DIA-36) talks to the agent over the `jarvis.diary` RPC.
 * It can only list the entries and delete one by id: entries come only from finished conversations.
 */
export const DIARY_RPC_METHOD = 'jarvis.diary';

export type DiaryRequest = { action: 'list' } | { action: 'forget'; id: string };
export type DiaryReply = DiaryData & { ok: boolean };
type Transport = (payload: string) => Promise<string>;

let transport: Transport | null = null;

/** Set by the live session while the agent is in the room; null when the link is down. */
export function setDiaryTransport(next: Transport | null) {
  transport = next;
}

export class DiaryOfflineError extends Error {
  constructor() {
    super('Sem link com o Jarvis: conecte-se para apagar do diário.');
    this.name = 'DiaryOfflineError';
  }
}

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []);

function toEntry(value: unknown): DiaryEntry | null {
  const raw = value as Partial<DiaryEntry>;
  if (typeof raw?.id !== 'string' || typeof raw.title !== 'string' || typeof raw.date !== 'string') return null;
  return {
    ...raw,
    id: raw.id,
    title: raw.title,
    date: raw.date,
    started_at: typeof raw.started_at === 'string' ? raw.started_at : '',
    asked: strings(raw.asked),
    decided: strings(raw.decided),
    pending: strings(raw.pending),
  };
}

export function parseDiaryReply(raw: string): DiaryReply {
  const data = JSON.parse(raw) as Partial<DiaryReply>;
  const items = Array.isArray(data.items) ? data.items.map(toEntry).filter((item): item is DiaryEntry => item !== null) : [];
  return {
    ok: data.ok === true,
    status: data.status ?? 'list',
    items,
    total: typeof data.total === 'number' ? data.total : items.length,
    query: data.query ?? null,
    period: data.period ?? null,
    search: data.search ?? null,
    message: data.message ?? null,
  };
}

const WEEKDAYS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];

/** "2026-10-19" → "segunda, 19/10" (or "hoje" / "ontem" next to `today`). */
export function diaryDayLabel(date: string, today = new Date()): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return date;
  const day = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const diff = Math.round((start.getTime() - day.getTime()) / 86_400_000);
  const short = `${match[3]}/${match[2]}`;
  if (diff === 0) return `hoje, ${short}`;
  if (diff === 1) return `ontem, ${short}`;
  return `${WEEKDAYS[day.getDay()]}, ${short}`;
}

/** "14:05" from the ISO start of the conversation. */
export function diaryClock(iso: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  return match ? `${match[1]}:${match[2]}` : '';
}

/** Entries grouped by day, in the order they came (newest first). */
export function groupByDay(items: DiaryEntry[]): { date: string; items: DiaryEntry[] }[] {
  const groups: { date: string; items: DiaryEntry[] }[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last?.date === item.date) last.items.push(item);
    else groups.push({ date: item.date, items: [item] });
  }
  return groups;
}

/** "pelo sentido · 82%", as in the Memória panel. */
export function diaryMatchLabel(item: Pick<DiaryEntry, 'match' | 'score'>): string {
  const how = item.match === 'meaning' ? 'pelo sentido' : 'pelas palavras';
  return typeof item.score === 'number' ? `${how} · ${Math.round(item.score * 100)}%` : how;
}

export function diaryDetail(data: DiaryData): string {
  const count = `${data.total} ${data.total === 1 ? 'conversa' : 'conversas'}`;
  const filter = [data.period, data.query ? `"${data.query}"` : null].filter(Boolean).join(' · ');
  return filter ? `${filter} · ${count}` : count;
}

/** Demo mode has no agent: the panel just drops the entry locally. */
function forgetLocally(current: DiaryData, id: string): DiaryReply {
  const removed = current.items.find((item) => item.id === id);
  return {
    ...current,
    ok: Boolean(removed),
    status: 'forgotten',
    items: current.items.filter((item) => item.id !== id),
    total: Math.max(0, current.total - (removed ? 1 : 0)),
    message: removed ? `Apagada: ${removed.title}` : 'Essa conversa já não estava no diário.',
  };
}

/** Deletes one entry (the panel's "apagar" button) and returns the panel's new contents. */
export async function forgetDiary(current: DiaryData, id: string): Promise<DiaryReply> {
  if (!transport) {
    if (useHud.getState().demo) return forgetLocally(current, id);
    throw new DiaryOfflineError();
  }
  const request: DiaryRequest = { action: 'forget', id };
  const reply = parseDiaryReply(await transport(JSON.stringify(request)));
  // A filtered panel ("o que eu fiz ontem?") stays filtered after the delete.
  if (current.query || current.period) {
    return { ...reply, query: current.query ?? null, period: current.period ?? null, search: current.search ?? null, items: current.items.filter((item) => item.id !== id) };
  }
  return reply;
}
