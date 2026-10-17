import { create } from 'zustand';
import { DEFAULT_HOME, locateHost } from './geo';
import type {
  CardDataMap,
  CardKind,
  GeoPoint,
  HudCard,
  HudPanelAction,
  JarvisMode,
  LinkKind,
  LogEntry,
  LogLevel,
  NetLink,
} from './types';

const MAX_CARDS = 4;
const MAX_LOG = 40;
const MAX_LINKS = 14;
const MAX_VOICE_STARTS = 60;
const LINK_TTL: Record<LinkKind, number> = { request: 5200, source: 6500, model: 3800, link: 4200 };

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
  /** Last time the agent reported hearing the user's voice. */
  userHeardAt: number | null;
  /** Client-side times at which the user started speaking (for transcript ordering). */
  voiceStarts: number[];
  home: GeoPoint;
  links: NetLink[];
  cards: (HudCard & { key: string })[];
  /** Card shown enlarged in the middle of the HUD. */
  expandedId: string | null;
  log: LogEntry[];
  setMode: (mode: JarvisMode) => void;
  setActiveTool: (name: string | null) => void;
  setDemo: (demo: boolean) => void;
  setUserHeardAt: (ts: number | null) => void;
  addVoiceStart: (ts: number) => void;
  resetVoice: () => void;
  setHome: (home: GeoPoint) => void;
  addLinks: (hosts: string[], kind: LinkKind) => void;
  pruneLinks: () => void;
  closeCards: (kinds: CardKind[]) => void;
  pushCard: <K extends CardKind>(kind: K, data: CardDataMap[K]) => void;
  dismissCard: (id: string) => void;
  clearCards: () => void;
  setExpanded: (id: string | null) => void;
  /** Executes a panel command from the agent and reports what really happened. */
  runPanelCommand: (action: HudPanelAction, kinds: CardKind[]) => { open: CardKind[]; changed: CardKind[] };
  addLog: (level: LogLevel, text: string) => void;
  clearLog: () => void;
}

export const useHud = create<HudState>((set, get) => ({
  mode: 'standby',
  activeTool: null,
  demo: false,
  userHeardAt: null,
  voiceStarts: [],
  home: DEFAULT_HOME,
  links: [],
  cards: [],
  expandedId: null,
  log: [],
  setMode: (mode) => set((s) => (s.mode === mode ? s : { mode })),
  setActiveTool: (activeTool) => set({ activeTool }),
  setDemo: (demo) => set({ demo }),
  setUserHeardAt: (userHeardAt) => set({ userHeardAt }),
  addVoiceStart: (ts) => set((s) => ({ voiceStarts: [...s.voiceStarts, ts].slice(-MAX_VOICE_STARTS) })),
  resetVoice: () => set({ voiceStarts: [], userHeardAt: null }),
  setHome: (home) => set({ home }),
  addLinks: (hosts, kind) =>
    set((s) => {
      const now = Date.now();
      const fresh = hosts.map((host, index) => {
        const place = locateHost(host);
        return {
          id: nextId('link'),
          host,
          label: place.name,
          lat: place.lat,
          lon: place.lon,
          kind,
          // Staggered so several connections fan out instead of firing at once.
          createdAt: now + index * 140,
          ttl: LINK_TTL[kind],
        };
      });
      const alive = s.links.filter((link) => now - link.createdAt < link.ttl + 1500);
      return { links: [...alive, ...fresh].slice(-MAX_LINKS) };
    }),
  pruneLinks: () =>
    set((s) => {
      const now = Date.now();
      const alive = s.links.filter((link) => now - link.createdAt < link.ttl + 1500);
      return alive.length === s.links.length ? s : { links: alive };
    }),
  closeCards: (kinds) => set((s) => ({ cards: s.cards.filter((card) => !kinds.includes(card.kind)), expandedId: null })),
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
  dismissCard: (id) =>
    set((s) => ({ cards: s.cards.filter((c) => c.id !== id), expandedId: s.expandedId === id ? null : s.expandedId })),
  clearCards: () => set({ cards: [], expandedId: null }),
  setExpanded: (expandedId) => set({ expandedId }),
  runPanelCommand: (action, kinds) => {
    const { cards } = get();
    const present = [...new Set(cards.map((card) => card.kind))];
    let changed: CardKind[] = [];
    if (action === 'close') {
      changed = present.filter((kind) => kinds.includes(kind));
      set((s) => ({
        cards: s.cards.filter((card) => !kinds.includes(card.kind)),
        expandedId: s.cards.some((card) => card.id === s.expandedId && kinds.includes(card.kind)) ? null : s.expandedId,
      }));
    } else if (action === 'close_all') {
      changed = present;
      set({ cards: [], expandedId: null });
    } else if (action === 'expand') {
      const target = cards.find((card) => kinds.includes(card.kind));
      if (target) {
        changed = [target.kind];
        set({ expandedId: target.id });
      }
    } else if (action === 'collapse') {
      set({ expandedId: null });
    }
    const open = [...new Set(get().cards.map((card) => card.kind))];
    return { open, changed };
  },
  addLog: (level, text) =>
    set((s) => ({
      log: [{ id: nextId('log'), ts: Date.now(), level, text }, ...s.log].slice(0, MAX_LOG),
    })),
  clearLog: () => set({ log: [] }),
}));
