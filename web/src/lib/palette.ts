/**
 * Paleta de comandos (Ctrl+K): uma lista só com tudo o que o HUD faz por clique (áreas, link,
 * microfone, personas, ajustes) e os protocolos do Jarvis, com um exemplo que vai por texto.
 */
import { PROTOCOLS } from './catalog';
import { guessKind, kindLabel } from './osint';
import type { HudPrefs, QualityPref } from './prefs';
import { QUALITY_LABELS } from './prefs';
import { THEMES, type ThemeId } from './themes';
import { VIEWS, type ViewId } from './views';

export interface PaletteCommand {
  id: string;
  group: string;
  label: string;
  hint?: string;
  /** Palavras a mais para a busca ("tema", "cor" para as personas). */
  keywords?: string;
  /** Atalho de teclado mostrado à direita. */
  shortcut?: string;
  /** Por que não dá para rodar agora; o comando aparece apagado. */
  disabled?: string;
  run: () => void;
}

export interface PaletteContext {
  view: ViewId;
  connected: boolean;
  demo: boolean;
  canConnect: boolean;
  busy: boolean;
  micEnabled: boolean;
  cinema: boolean;
  prefs: Pick<HudPrefs, 'theme' | 'quality' | 'captions' | 'ambient' | 'reactorHum'>;
  /** Ferramentas ligadas no servidor (null: servidor fora do ar, mostra todas). */
  enabledTools: string[] | null;
  hasCards: boolean;
  setView: (view: ViewId) => void;
  start: () => void;
  stop: () => void;
  toggleMic: () => void;
  startDemo: () => void;
  setCinema: (on: boolean) => void;
  setPrefs: (next: Partial<HudPrefs>) => void;
  resetLayout: () => void;
  clearCards: () => void;
  /** Manda um texto ao Jarvis pelo link aberto. */
  send: (text: string) => void;
  /** FOC-47: a sessão de foco está rodando; começar e parar. */
  focusRunning?: boolean;
  startFocus?: () => void;
  stopFocus?: () => void;
}

const NEEDS_LINK = 'Inicie o link para enviar';

export function normalizeText(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

/** A primeira frase de exemplo de um protocolo, sem as aspas: “Abra o Spotify.” · “Feche…” → Abra o Spotify. */
export function examplePhrase(hint: string): string {
  const first = hint.split('·')[0] ?? '';
  return first.replace(/[“”"]/g, '').trim();
}

export function buildCommands(ctx: PaletteContext): PaletteCommand[] {
  const commands: PaletteCommand[] = [];
  const canSend = ctx.connected && !ctx.demo;

  for (const view of VIEWS) {
    commands.push({
      id: `view:${view.id}`,
      group: 'Ir para',
      label: view.label,
      hint: view.hint,
      keywords: 'abrir area aba tela',
      shortcut: view.key,
      disabled: ctx.view === view.id ? 'Você já está aqui' : undefined,
      run: () => ctx.setView(view.id),
    });
  }

  if (ctx.connected || ctx.demo) {
    commands.push({
      id: 'link:stop',
      group: 'Link',
      label: ctx.demo ? 'Sair da simulação' : 'Encerrar link',
      keywords: 'desligar parar fechar tchau',
      run: ctx.stop,
    });
  } else {
    commands.push({
      id: 'link:start',
      group: 'Link',
      label: 'Inicializar link',
      hint: 'Abre a conversa por voz',
      keywords: 'iniciar conectar falar comecar ligar',
      shortcut: 'Espaço',
      disabled: ctx.busy ? 'Conectando…' : ctx.canConnect ? undefined : 'Configure o LiveKit no .env',
      run: ctx.start,
    });
    commands.push({
      id: 'link:demo',
      group: 'Link',
      label: 'Iniciar simulação',
      hint: 'Conversa roteirizada com dados fictícios',
      keywords: 'demo demonstracao teste',
      run: ctx.startDemo,
    });
  }
  if (canSend) {
    commands.push({
      id: 'link:mic',
      group: 'Link',
      label: ctx.micEnabled ? 'Silenciar microfone' : 'Ativar microfone',
      keywords: 'mudo mute mic',
      shortcut: 'M',
      run: ctx.toggleMic,
    });
  }

  if (ctx.startFocus && ctx.stopFocus) {
    commands.push(
      ctx.focusRunning
        ? { id: 'focus:stop', group: 'Dia a dia', label: 'Encerrar o foco', keywords: 'pomodoro parar sessao', run: ctx.stopFocus }
        : {
            id: 'focus:start',
            group: 'Dia a dia',
            label: 'Começar o foco',
            hint: 'Pomodoro com os tempos do painel Foco',
            keywords: 'pomodoro concentracao timer sessao iniciar',
            run: ctx.startFocus,
          },
    );
  }

  commands.push({
    id: 'look:cinema',
    group: 'Aparência',
    label: ctx.cinema ? 'Sair do modo cinema' : 'Modo cinema',
    hint: 'Só o núcleo e a legenda',
    keywords: 'tela cheia esconder paineis foco',
    shortcut: 'F',
    run: () => {
      ctx.setView('home');
      ctx.setCinema(!ctx.cinema);
    },
  });
  for (const theme of THEMES) {
    commands.push({
      id: `theme:${theme.id}`,
      group: 'Persona',
      label: theme.label,
      hint: theme.hint,
      keywords: 'tema cor persona voz trocar',
      disabled: ctx.prefs.theme === theme.id ? 'Persona ativa' : undefined,
      run: () => ctx.setPrefs({ theme: theme.id as ThemeId }),
    });
  }
  const toggles: { key: 'captions' | 'ambient' | 'reactorHum'; label: string; keywords: string }[] = [
    { key: 'captions', label: 'Legenda ao vivo', keywords: 'legenda fala texto' },
    { key: 'ambient', label: 'Modo ambiente', keywords: 'relogio descanso ocioso' },
    { key: 'reactorHum', label: 'Som do reator', keywords: 'zumbido audio' },
  ];
  for (const toggle of toggles) {
    const on = ctx.prefs[toggle.key];
    commands.push({
      id: `toggle:${toggle.key}`,
      group: 'Aparência',
      label: `${toggle.label}: ${on ? 'desligar' : 'ligar'}`,
      keywords: toggle.keywords,
      run: () => ctx.setPrefs({ [toggle.key]: !on } as Partial<HudPrefs>),
    });
  }
  for (const quality of Object.keys(QUALITY_LABELS) as QualityPref[]) {
    commands.push({
      id: `quality:${quality}`,
      group: 'Aparência',
      label: `Qualidade da cena: ${QUALITY_LABELS[quality]}`,
      keywords: 'fps desempenho lento graficos',
      disabled: ctx.prefs.quality === quality ? 'Em uso' : undefined,
      run: () => ctx.setPrefs({ quality }),
    });
  }
  commands.push({
    id: 'look:layout',
    group: 'Aparência',
    label: 'Restaurar painéis',
    hint: 'Volta as colunas do Painel ao padrão',
    keywords: 'layout resetar colunas',
    run: ctx.resetLayout,
  });
  if (ctx.hasCards) {
    commands.push({
      id: 'look:clear',
      group: 'Aparência',
      label: 'Limpar projeções',
      keywords: 'fechar paineis cards',
      shortcut: 'Esc',
      run: ctx.clearCards,
    });
  }

  for (const protocol of PROTOCOLS) {
    const on = ctx.enabledTools === null || ctx.enabledTools.includes(protocol.id);
    const phrase = examplePhrase(protocol.hint);
    commands.push({
      id: `protocol:${protocol.id}`,
      group: 'Protocolos',
      label: protocol.label,
      hint: phrase ? `“${phrase}”` : undefined,
      keywords: `${protocol.code} ${protocol.hint}`,
      disabled: !on ? 'Desativado no .env' : canSend ? undefined : NEEDS_LINK,
      run: () => ctx.send(phrase),
    });
  }
  return commands;
}

function score(command: PaletteCommand, words: string[]): number {
  const label = normalizeText(command.label);
  const rest = normalizeText(`${command.group} ${command.hint ?? ''} ${command.keywords ?? ''}`);
  let total = 0;
  for (const word of words) {
    if (label.startsWith(word)) total += 4;
    else if (label.split(' ').some((part) => part.startsWith(word))) total += 3;
    else if (label.includes(word)) total += 2;
    else if (rest.includes(word)) total += 1;
    else return 0;
  }
  return total;
}

/** Os comandos que casam com o que foi digitado, do melhor para o pior; sem texto, todos na ordem. */
export function searchCommands(commands: PaletteCommand[], query: string): PaletteCommand[] {
  const words = normalizeText(query).split(' ').filter(Boolean);
  if (words.length === 0) return commands;
  return commands
    .map((command, index) => ({ command, index, value: score(command, words) }))
    .filter((item) => item.value > 0)
    .sort((a, b) => Number(Boolean(a.command.disabled)) - Number(Boolean(b.command.disabled)) || b.value - a.value || a.index - b.index)
    .map((item) => item.command);
}

/** "Consultar no Olho de Deus" quando o texto tem cara de IP, domínio, link, CNPJ, CEP ou email. */
export function osintCommand(query: string, enabled: boolean, consult: (target: string) => void): PaletteCommand | null {
  const text = query.trim();
  const kind = guessKind(text);
  // Um nome solto (usuário) ou dois dígitos (DDD) casam com quase tudo que se digita: ficam para a área.
  if (!enabled || !kind || kind === 'username' || kind === 'ddd') return null;
  return {
    id: 'osint:lookup',
    group: 'Olho de Deus',
    label: `Consultar ${kindLabel(kind)}: ${text.length > 48 ? `${text.slice(0, 47)}…` : text}`,
    hint: 'Fontes públicas',
    run: () => consult(text),
  };
}

/** "Enviar ao Jarvis" com o texto digitado, quando há um link aberto para recebê-lo. */
export function freeTextCommand(ctx: Pick<PaletteContext, 'connected' | 'demo' | 'send'>, query: string): PaletteCommand | null {
  const text = query.trim();
  if (text.length < 2) return null;
  const canSend = ctx.connected && !ctx.demo;
  return {
    id: 'send:text',
    group: 'Jarvis',
    label: `Enviar ao Jarvis: “${text}”`,
    disabled: canSend ? undefined : NEEDS_LINK,
    run: () => ctx.send(text),
  };
}
