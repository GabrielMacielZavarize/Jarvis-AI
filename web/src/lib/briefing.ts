/** Briefing do Painel: a saudação pela hora e as frases de exemplo que viram atalhos. */
import { PROTOCOLS } from './catalog';
import { examplePhrase } from './palette';

/** "Boa madrugada" até as 5h, "Bom dia" até o meio-dia, "Boa tarde" até as 18h, depois "Boa noite". */
export function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 5) return 'Boa madrugada';
  if (hour < 12) return 'Bom dia';
  if (hour < 18) return 'Boa tarde';
  return 'Boa noite';
}

export interface Suggestion {
  id: string;
  code: string;
  phrase: string;
}

/**
 * Até `count` frases de exemplo dos protocolos ligados. A lista gira com o dia, para o Painel
 * lembrar de coisas diferentes ao longo da semana em vez de mostrar sempre as três primeiras.
 */
export function suggestions(enabledTools: string[] | null, now: Date, count = 3): Suggestion[] {
  const available = PROTOCOLS.filter((protocol) => enabledTools === null || enabledTools.includes(protocol.id))
    .map((protocol) => ({ id: protocol.id, code: protocol.code, phrase: examplePhrase(protocol.hint) }))
    // Encerrar a sessão e as frases muito longas não ajudam como atalho.
    .filter((item) => item.id !== 'end_session' && item.phrase.length > 0 && item.phrase.length <= 44);
  if (available.length <= count) return available;
  const day = Math.floor((now.getTime() - now.getTimezoneOffset() * 60_000) / 86_400_000);
  const start = (day * count) % available.length;
  return Array.from({ length: count }, (_, index) => available[(start + index) % available.length]);
}
