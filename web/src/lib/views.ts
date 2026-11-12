/**
 * Áreas de trabalho do HUD: o que as abas do topo (e a barra de baixo, no celular) abrem.
 * "home" é o HUD de sempre, com o núcleo no centro; as outras abrem painéis por cima dele.
 */
export type ViewId = 'home' | 'system' | 'settings';

export interface ViewInfo {
  id: ViewId;
  label: string;
  /** O que a área mostra, na dica da aba e na paleta de comandos. */
  hint: string;
  /** Tecla que abre a área quando o foco não está num campo de texto. */
  key: string;
}

export const VIEWS: ViewInfo[] = [
  { id: 'home', label: 'Painel', hint: 'Núcleo, briefing do dia, conversa e projeções', key: '1' },
  { id: 'system', label: 'Sistema', hint: 'Estado do link, protocolos, saúde, gestos e celular', key: '2' },
  { id: 'settings', label: 'Ajustes', hint: 'Persona, cena, áudio, microfone e atalhos', key: '3' },
];

export const DEFAULT_VIEW: ViewId = 'home';

export function isView(value: unknown): value is ViewId {
  return VIEWS.some((view) => view.id === value);
}

export function viewInfo(id: ViewId): ViewInfo {
  return VIEWS.find((view) => view.id === id) ?? VIEWS[0];
}

/** A área que uma tecla abre ("1" → Painel), ou null. */
export function viewForKey(key: string): ViewId | null {
  return VIEWS.find((view) => view.key === key)?.id ?? null;
}
