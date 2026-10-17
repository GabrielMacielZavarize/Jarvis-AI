import { create } from 'zustand';
import type { CardDataMap, CardKind, HudCard, JarvisMode, LogEntry, LogLevel } from './types';

const MAX_CARDS = 4;
const MAX_LOG = 40;

let counter = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter++).toString(36)}`;

/** Cards with the same key replace each other instead of stacking. */
function cardKey(kind: CardKind, data: CardDataMap[CardKind]): string {
  if (kind === 'timer') return `timer:${(data as CardDataMap['timer']).id}`;
  if (kind === 'note') return `note:${(data as CardDataMap['note']).title}`;
  return kind;
}

interface HudState {
  mode: JarvisMode;
  activeTool: string | null;
  demo: boolean;
  cards: (HudCard & { key: string })[];
  log: LogEntry[];
  setMode: (mode: JarvisMode) => void;
  setActiveTool: (name: string | null) => void;
  setDemo: (demo: boolean) => void;
  pushCard: <K extends CardKind>(kind: K, data: CardDataMap[K]) => void;
  dismissCard: (id: string) => void;
  clearCards: () => void;
  addLog: (level: LogLevel, text: string) => void;
  clearLog: () => void;
}

export const useHud = create<HudState>((set) => ({
  mode: 'standby',
  activeTool: null,
  demo: false,
  cards: [],
  log: [],
  setMode: (mode) => set((s) => (s.mode === mode ? s : { mode })),
  setActiveTool: (activeTool) => set({ activeTool }),
  setDemo: (demo) => set({ demo }),
  pushCard: (kind, data) =>
    set((s) => {
      const key = cardKey(kind, data);
      const existing = s.cards.find((c) => c.key === key);
      const card = {
        id: existing?.id ?? nextId('card'),
        key,
        kind,
        data,
        createdAt: Date.now(),
      } as HudCard & { key: string };
      const others = s.cards.filter((c) => c.key !== key);
      return { cards: [card, ...others].slice(0, MAX_CARDS) };
    }),
  dismissCard: (id) => set((s) => ({ cards: s.cards.filter((c) => c.id !== id) })),
  clearCards: () => set({ cards: [] }),
  addLog: (level, text) =>
    set((s) => ({
      log: [{ id: nextId('log'), ts: Date.now(), level, text }, ...s.log].slice(0, MAX_LOG),
    })),
  clearLog: () => set({ log: [] }),
}));
