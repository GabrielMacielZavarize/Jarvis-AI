import { formatDuration } from './format';
import type { CardKind, HudCard, HudPanelAction, HudRequest, PanelInfo } from './types';

/**
 * Code, title shown on screen and spoken aliases of every HUD panel.
 * The user calls these panels "abas"/"abinhas"; the titles must match tools.HUD_PANEL_KINDS.
 */
export const PANEL_META: Record<CardKind, { code: string; title: string; aliases: string[] }> = {
  weather: { code: 'WX-01', title: 'Meteorologia', aliases: ['clima', 'tempo', 'previsao'] },
  search: { code: 'NET-02', title: 'Pesquisa', aliases: ['busca', 'resultados'] },
  news: { code: 'NWS-03', title: 'Notícias', aliases: ['noticia', 'manchetes'] },
  time: { code: 'CHR-04', title: 'Cronometria', aliases: ['horario', 'hora', 'relogio', 'fuso'] },
  diagnostics: { code: 'SYS-05', title: 'Diagnóstico', aliases: ['sistema', 'cpu', 'ram', 'desempenho'] },
  timer: { code: 'TMR-06', title: 'Timer', aliases: ['cronometro', 'temporizador', 'contagem', 'alarme'] },
  note: { code: 'HUD-07', title: 'Nota', aliases: ['notas', 'anotacao', 'lista', 'rascunho'] },
  email: { code: 'COM-12', title: 'Email', aliases: ['e-mail', 'rascunho', 'mensagem'] },
  media: { code: 'MED-08', title: 'Reprodução', aliases: ['midia', 'video', 'musica', 'player', 'tocando'] },
  screen: { code: 'VIS-14', title: 'Leitura de tela', aliases: ['print', 'captura', 'screenshot'] },
  install: { code: 'APP-15', title: 'Instalação de app', aliases: ['instalacao', 'instalar', 'aplicativo', 'winget', 'download'] },
  camera: { code: 'CAM-19', title: 'Câmera', aliases: ['webcam', 'camara', 'cam', 'feed', 'visao', 'olho'] },
  pointer: { code: 'MOU-20', title: 'Mouse e teclado', aliases: ['mouse', 'teclado', 'clique', 'cursor', 'digitacao', 'atalho'] },
  memory: { code: 'MEM-23', title: 'Memória', aliases: ['memorias', 'lembranca', 'lembrancas', 'perfil', 'sobre mim'] },
  explain: { code: 'TEL-31', title: 'Assistente de tela', aliases: ['explicacao', 'erro', 'correcao', 'codigo', 'resumo', 'traducao'] },
  routine: { code: 'ROT-24', title: 'Rotina', aliases: ['rotinas', 'modo', 'passos', 'sequencia'] },
};

const PANEL_ACTIONS: HudPanelAction[] = ['list', 'close', 'close_all', 'expand', 'collapse'];
const EMAIL_STATUS = { address: 'confirmando endereço', draft: 'rascunho', sent: 'enviado', cancelled: 'cancelado' } as const;

// Filler words of spoken requests ("feche essa aba de reprodução aqui").
const STOPWORDS = new Set(
  (
    'a o as os de da do das dos e em no na nos nas um uma que pra para com por esse essa este esta isso ' +
    'aquele aquela aba abas abinha abinhas painel paineis janela janelas aqui ali la ai tab panel card'
  ).split(' '),
);
const LAST_WORDS = new Set(['last', 'latest', 'ultimo', 'ultima', 'recente', 'mais', 'novo', 'nova']);

export function panelTitle(card: HudCard): string {
  if (card.kind === 'note') return card.data.title || PANEL_META.note.title;
  return PANEL_META[card.kind].title;
}

/** Short subtitle that tells two panels of the same kind apart (city, query, timer label...). */
export function panelDetail(card: HudCard, now = Date.now()): string {
  switch (card.kind) {
    case 'weather':
      return card.data.location;
    case 'search':
      return `"${card.data.query}"`;
    case 'news':
      return card.data.topic;
    case 'time':
      return card.data.location;
    case 'diagnostics':
      return card.data.hostname;
    case 'timer': {
      const { label, status, ends_at: endsAt } = card.data;
      if (status === 'done' || (endsAt != null && endsAt <= now)) return `${label} · concluído`;
      return endsAt != null ? `${label} · faltam ${formatDuration((endsAt - now) / 1000)}` : label;
    }
    case 'note':
      return '';
    case 'email':
      return [card.data.subject, EMAIL_STATUS[card.data.status]].filter(Boolean).join(' · ');
    case 'media':
      return [card.data.service, card.data.title].filter(Boolean).join(' · ');
    case 'screen':
      return card.data.label;
    case 'install':
      return [card.data.package?.name ?? card.data.query, card.data.status].filter(Boolean).join(' · ');
    case 'camera':
      return card.data.takenAt ? `ao vivo · quadro analisado ${new Date(card.data.takenAt).toLocaleTimeString('pt-BR')}` : 'ao vivo';
    case 'pointer':
      return [card.data.action, card.data.label || card.data.target].filter(Boolean).join(' · ');
    case 'memory': {
      const { query, total } = card.data;
      const count = `${total} ${total === 1 ? 'memória' : 'memórias'}`;
      return query ? `"${query}" · ${count}` : count;
    }
    case 'explain':
      return [card.data.task_label, card.data.title || card.data.source].filter(Boolean).join(' · ');
    case 'routine': {
      const done = card.data.steps.filter((step) => step.status === 'ok').length;
      return `${card.data.name} · ${done}/${card.data.steps.length}`;
    }
  }
}

export function describePanel(card: HudCard, expandedId: string | null = null, now = Date.now()): PanelInfo {
  return { id: card.id, kind: card.kind, title: panelTitle(card), detail: panelDetail(card, now), expanded: card.id === expandedId };
}

function normalize(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

function tokens(text: string): string[] {
  return normalize(text).split(/[^a-z0-9]+/).filter(Boolean);
}

/** "nota" ≈ "notas", "compra" ≈ "compras": prefix match for words with 4+ letters. */
function sameWord(a: string, b: string): boolean {
  if (a === b) return true;
  return Math.min(a.length, b.length) >= 4 && (a.startsWith(b) || b.startsWith(a));
}

function haystack(card: HudCard, now: number): string[] {
  const meta = PANEL_META[card.kind];
  return tokens([card.kind, meta.title, ...meta.aliases, panelTitle(card), panelDetail(card, now)].join(' '));
}

function newest(cards: HudCard[]): HudCard {
  return cards.reduce((best, card) => (card.createdAt > best.createdAt ? card : best));
}

function isKind(text: string): text is CardKind {
  return text in PANEL_META;
}

/**
 * Panels one spoken reference points to: a kind ("screen"), "last"/"último" (most recent panel)
 * or words of the title/subject shown on it ("rascunho lista de compras estrogonofe").
 */
function matchTarget(cards: HudCard[], target: string, now: number): HudCard[] {
  const text = normalize(target).trim();
  if (!text || cards.length === 0) return [];
  if (isKind(text)) return cards.filter((card) => card.kind === text);

  const words = tokens(text).filter((word) => !STOPWORDS.has(word));
  if (words.length === 0) return [];
  if (words.every((word) => LAST_WORDS.has(word))) return [newest(cards)];

  let best = 0;
  let winners: HudCard[] = [];
  for (const card of cards) {
    const hay = haystack(card, now);
    const score = words.filter((word) => hay.some((other) => sameWord(word, other))).length / words.length;
    if (score > best) {
      best = score;
      winners = [card];
    } else if (score > 0 && score === best) {
      winners.push(card);
    }
  }
  if (best < 0.5) return [];
  // A full match ("notas", "timer") means every such panel; a partial one only the most recent.
  return best === 1 ? winners : [newest(winners)];
}

export function matchPanels(
  cards: HudCard[],
  targets: string[],
  now = Date.now(),
): { matched: HudCard[]; unmatched: string[] } {
  const picked = new Map<string, HudCard>();
  const unmatched: string[] = [];
  for (const target of targets) {
    const found = matchTarget(cards, target, now);
    if (found.length === 0) unmatched.push(target);
    for (const card of found) picked.set(card.id, card);
  }
  // Newest first, like the column on screen.
  const matched = [...picked.values()].sort((a, b) => b.createdAt - a.createdAt);
  return { matched, unmatched };
}

/** Parses the agent's RPC payload; older agents sent `kinds` instead of `targets`. */
export function parseHudRequest(payload: string): HudRequest {
  let raw: { action?: unknown; targets?: unknown; kinds?: unknown } = {};
  try {
    raw = JSON.parse(payload || '{}') ?? {};
  } catch {
    raw = {};
  }
  if (raw.action === 'mic' || raw.action === 'end_session') return { action: raw.action };
  const action = PANEL_ACTIONS.includes(raw.action as HudPanelAction) ? (raw.action as HudPanelAction) : 'list';
  const list = Array.isArray(raw.targets) ? raw.targets : Array.isArray(raw.kinds) ? raw.kinds : [];
  return { action, targets: list.filter((item): item is string => typeof item === 'string') };
}
