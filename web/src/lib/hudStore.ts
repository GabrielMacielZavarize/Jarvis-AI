import { create } from 'zustand';
import { DEFAULT_HOME, locateHost } from './geo';
import { describePanel, matchPanels } from './panels';
import type {
  CameraState,
  DictationState,
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
  PanelCommandResult,
} from './types';

const MAX_CARDS = 4;
const MAX_LOG = 40;
const MAX_LINKS = 14;
const MAX_VOICE_STARTS = 60;
const LINK_TTL: Record<LinkKind, number> = { request: 5200, source: 6500, model: 3800, link: 4200 };

let counter = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter++).toString(36)}`;

type StoredCard = HudCard & { key: string };

/** Cards that must not scroll away: anything waiting for a spoken code, running timers and the live camera. */
function isPinned(card: HudCard, now: number): boolean {
  if (card.kind === 'camera') return true;
  if (card.kind === 'email') return card.data.status === 'draft';
  if (card.kind === 'pointer') return card.data.status === 'pending';
  if (card.kind === 'timer') return card.data.status === 'running' && (card.data.ends_at == null || card.data.ends_at > now);
  return false;
}

/** Keeps at most MAX_CARDS (newest first), dropping the oldest unpinned cards before pinned ones. */
export function trimCards<T extends HudCard>(cards: T[], now = Date.now()): T[] {
  const kept = [...cards];
  for (let index = kept.length - 1; index > 0 && kept.length > MAX_CARDS; index--) {
    if (!isPinned(kept[index], now)) kept.splice(index, 1);
  }
  return kept.slice(0, MAX_CARDS);
}

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
  cards: StoredCard[];
  /** Card shown enlarged in the middle of the HUD. */
  expandedId: string | null;
  log: LogEntry[];
  /** Webcam state polled from the server (null: server unreachable). */
  camera: CameraState | null;
  /** Dictation mode (DIT-29) shown by the DITADO indicator. */
  dictation: DictationState | null;
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
  /** New data for a card that stays where it is (the Memória panel after its delete button). */
  updateCard: <K extends CardKind>(id: string, kind: K, data: CardDataMap[K]) => void;
  clearCards: () => void;
  setExpanded: (id: string | null) => void;
  /**
   * Executes a panel command from the agent and reports what really happened.
   * Targets are kinds ("screen"), "last" or words of the title shown on the panel.
   */
  runPanelCommand: (action: HudPanelAction, targets: string[]) => PanelCommandResult;
  addLog: (level: LogLevel, text: string) => void;
  clearLog: () => void;
  setCamera: (camera: CameraState | null) => void;
  setDictation: (dictation: DictationState | null) => void;
  /** Opens the Câmera panel unless it is already on screen (keeps the analysed frame). */
  openCamera: () => void;
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
  camera: null,
  dictation: null,
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
      } as StoredCard;
      const others = s.cards.filter((c) => c.key !== key);
      const cards = trimCards([card, ...others]);
      return { cards, expandedId: cards.some((c) => c.id === s.expandedId) ? s.expandedId : null };
    }),
  dismissCard: (id) =>
    set((s) => ({ cards: s.cards.filter((c) => c.id !== id), expandedId: s.expandedId === id ? null : s.expandedId })),
  updateCard: (id, kind, data) =>
    set((s) => ({
      cards: s.cards.map((card) => (card.id === id && card.kind === kind ? ({ ...card, data } as StoredCard) : card)),
    })),
  clearCards: () => set({ cards: [], expandedId: null }),
  setExpanded: (expandedId) => set({ expandedId }),
  runPanelCommand: (action, targets) => {
    const { cards, expandedId } = get();
    const now = Date.now();
    let changed: HudCard[] = [];
    let unmatched: string[] = [];
    if (action === 'close' || action === 'expand') {
      const found = matchPanels(cards, targets, now);
      unmatched = found.unmatched;
      changed = action === 'expand' ? found.matched.slice(0, 1) : found.matched;
    }
    if (action === 'close') {
      const ids = new Set(changed.map((card) => card.id));
      set((s) => ({
        cards: s.cards.filter((card) => !ids.has(card.id)),
        expandedId: s.expandedId && ids.has(s.expandedId) ? null : s.expandedId,
      }));
    } else if (action === 'close_all') {
      changed = cards;
      set({ cards: [], expandedId: null });
    } else if (action === 'expand') {
      if (changed.length > 0) set({ expandedId: changed[0].id });
    } else if (action === 'collapse') {
      changed = cards.filter((card) => card.id === expandedId);
      set({ expandedId: null });
    }
    const state = get();
    return {
      open: state.cards.map((card) => describePanel(card, state.expandedId, now)),
      changed: changed.map((card) => describePanel(card, state.expandedId, now)),
      unmatched,
    };
  },
  addLog: (level, text) =>
    set((s) => ({
      log: [{ id: nextId('log'), ts: Date.now(), level, text }, ...s.log].slice(0, MAX_LOG),
    })),
  clearLog: () => set({ log: [] }),
  setCamera: (camera) => set({ camera }),
  setDictation: (dictation) => set({ dictation }),
  openCamera: () => {
    if (!get().cards.some((card) => card.kind === 'camera')) get().pushCard('camera', {});
  },
}));
