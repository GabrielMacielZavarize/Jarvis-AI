/**
 * Dia a dia no HUD: tarefas e notas (TAR-43), o briefing (BRF-46) e o teste de rede (RED-45).
 * Os dados moram no servidor do Jarvis; aqui ficam as chamadas, o que está na tela e a formatação.
 */
import { useEffect, useState } from 'react';
import { create } from 'zustand';
import type { BriefingData, SpeedData, TasksData } from './types';

export const BRIEFING_REFRESH_MS = 5 * 60_000;

async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    // Sem corpo JSON: fica a mensagem genérica.
  }
  return `O servidor respondeu ${response.status}.`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...init, headers: init?.body ? { 'Content-Type': 'application/json' } : undefined });
  if (!response.ok) throw new Error(await detail(response));
  return (await response.json()) as T;
}

const message = (error: unknown) => (error instanceof Error && error.message ? error.message : 'Não deu certo.');

/** "1.234,56" */
export function formatNumber(value: number, decimals = 2): string {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Moeda em reais: bitcoin sem centavos, dólar com dois, o que vale centavos com quatro. */
export function formatQuote(value: number): string {
  return `R$ ${formatNumber(value, value >= 1000 ? 0 : value >= 0.1 ? 2 : 4)}`;
}

export function formatChange(pct: number | null): { text: string; tone: 'up' | 'down' | 'flat' } {
  if (pct === null || !Number.isFinite(pct)) return { text: '', tone: 'flat' };
  const tone = pct > 0.005 ? 'up' : pct < -0.005 ? 'down' : 'flat';
  return { text: `${pct > 0 ? '+' : ''}${formatNumber(pct, 2)}%`, tone };
}

/** "3 abertas · 1 atrasada · 2 para hoje" */
export function tasksSummary(data: Pick<TasksData, 'open' | 'overdue' | 'due_today' | 'done_today'>): string {
  if (data.open === 0) return data.done_today > 0 ? `Tudo feito · ${data.done_today} hoje` : 'Nada pendente';
  const parts = [`${data.open} ${data.open === 1 ? 'aberta' : 'abertas'}`];
  if (data.overdue > 0) parts.push(`${data.overdue} ${data.overdue === 1 ? 'atrasada' : 'atrasadas'}`);
  if (data.due_today > 0) parts.push(`${data.due_today} para hoje`);
  return parts.join(' · ');
}

interface TasksStore {
  data: TasksData | null;
  /** false quando o servidor tem JARVIS_ENABLE_DAY=false. */
  enabled: boolean;
  error: string | null;
  load: () => Promise<void>;
  add: (text: string, kind: 'task' | 'note', due?: string) => Promise<boolean>;
  toggle: (id: string, done: boolean) => Promise<void>;
  remove: (id: string) => Promise<void>;
  /** O painel que o Jarvis acabou de projetar por voz. */
  set: (data: TasksData) => void;
}

type TasksReply = TasksData & { enabled: boolean };

export const useTasks = create<TasksStore>((set, get) => {
  const apply = (reply: TasksReply) => set({ data: reply, enabled: reply.enabled, error: null });
  const guard = async (work: () => Promise<TasksReply>): Promise<boolean> => {
    try {
      apply(await work());
      return true;
    } catch (error) {
      set({ error: message(error) });
      return false;
    }
  };
  return {
    data: null,
    enabled: true,
    error: null,
    load: async () => void (await guard(() => call<TasksReply>('/api/tasks'))),
    add: (text, kind, due) => guard(() => call<TasksReply>('/api/tasks', { method: 'POST', body: JSON.stringify({ text, kind, due: due || null }) })),
    toggle: async (id, done) => {
      // A caixa marca na hora; a resposta do servidor confirma (ou desfaz, se ele recusar).
      const before = get().data;
      if (before) set({ data: { ...before, tasks: before.tasks.map((task) => (task.id === id ? { ...task, done } : task)) } });
      const ok = await guard(() => call<TasksReply>(`/api/tasks/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ done }) }));
      if (!ok && before) set({ data: before });
    },
    remove: async (id) => void (await guard(() => call<TasksReply>(`/api/tasks/${encodeURIComponent(id)}`, { method: 'DELETE' }))),
    set: (data) => set({ data, enabled: true, error: null }),
  };
});

/** O resumo do dia, pedido de novo a cada 5 minutos enquanto `active`. */
export function useBriefing(active: boolean): BriefingData | null {
  const [data, setData] = useState<BriefingData | null>(null);
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const load = async () => {
      try {
        const next = await call<BriefingData>('/api/briefing');
        if (!cancelled) setData(next);
      } catch {
        // Servidor fora do ar: o painel mostra o que já tinha.
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), BRIEFING_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active]);
  return data;
}

interface SpeedStore {
  data: SpeedData | null;
  running: boolean;
  error: string | null;
  load: () => Promise<void>;
  test: () => Promise<void>;
  set: (data: SpeedData) => void;
}

export const useSpeed = create<SpeedStore>((set, get) => ({
  data: null,
  running: false,
  error: null,
  load: async () => {
    try {
      set({ data: await call<SpeedData>('/api/network'), error: null });
    } catch (error) {
      set({ error: message(error) });
    }
  },
  test: async () => {
    if (get().running) return;
    set({ running: true, error: null });
    try {
      set({ data: await call<SpeedData>('/api/network/test', { method: 'POST' }), running: false });
    } catch (error) {
      set({ running: false, error: message(error) });
    }
  },
  set: (data) => set({ data, error: null }),
}));
