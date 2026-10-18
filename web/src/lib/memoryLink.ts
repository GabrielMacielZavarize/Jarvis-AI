import { useHud } from './hudStore';
import type { MemoryData, MemoryItem } from './types';

/**
 * The Memória panel (MEM-23) talks to the agent over the `jarvis.memory` RPC.
 * It can only list memories and forget one by id: new memories come only from the user's voice.
 */
export const MEMORY_RPC_METHOD = 'jarvis.memory';

export type MemoryRequest = { action: 'list' } | { action: 'forget'; id: string };
export type MemoryReply = MemoryData & { ok: boolean };
type Transport = (payload: string) => Promise<string>;

let transport: Transport | null = null;

/** Set by the live session while the agent is in the room; null when the link is down. */
export function setMemoryTransport(next: Transport | null) {
  transport = next;
}

export class MemoryOfflineError extends Error {
  constructor() {
    super('Sem link com o Jarvis: conecte-se para apagar memórias.');
    this.name = 'MemoryOfflineError';
  }
}

function isItem(value: unknown): value is MemoryItem {
  const item = value as MemoryItem;
  return typeof item?.id === 'string' && typeof item.fact === 'string';
}

export function parseMemoryReply(raw: string): MemoryReply {
  const data = JSON.parse(raw) as Partial<MemoryReply>;
  const items = Array.isArray(data.items) ? data.items.filter(isItem) : [];
  return {
    ok: data.ok === true,
    status: data.status ?? 'list',
    items,
    total: typeof data.total === 'number' ? data.total : items.length,
    query: data.query ?? null,
    highlight: data.highlight ?? null,
    message: data.message ?? null,
  };
}

/** Demo mode has no agent: the panel just drops the item locally. */
function forgetLocally(current: MemoryData, id: string): MemoryReply {
  const removed = current.items.find((item) => item.id === id);
  const items = current.items.filter((item) => item.id !== id);
  return {
    ok: Boolean(removed),
    status: 'forgotten',
    items,
    total: Math.max(0, current.total - (removed ? 1 : 0)),
    query: current.query ?? null,
    highlight: null,
    message: removed ? `Esquecido: ${removed.fact}` : 'Essa memória já não existia.',
  };
}

/** Deletes one memory (the panel's "apagar" button) and returns the panel's new contents. */
export async function forgetMemory(current: MemoryData, id: string): Promise<MemoryReply> {
  if (!transport) {
    if (useHud.getState().demo) return forgetLocally(current, id);
    throw new MemoryOfflineError();
  }
  const request: MemoryRequest = { action: 'forget', id };
  const reply = parseMemoryReply(await transport(JSON.stringify(request)));
  // A filtered panel ("o que você sabe sobre música?") stays filtered after the delete.
  if (current.query) {
    const kept = new Set(current.items.map((item) => item.id));
    return { ...reply, query: current.query, items: reply.items.filter((item) => kept.has(item.id)) };
  }
  return reply;
}
