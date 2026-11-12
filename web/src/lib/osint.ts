/**
 * Olho de Deus (ODD-42) no HUD: adivinha a consulta pelo formato do texto, confere senha vazada
 * sem a senha sair do navegador e guarda os resultados da sessão. Quem consulta de verdade é o
 * servidor (osint.py); aqui o palpite só serve para mostrar o tipo antes do Enter.
 */
import { create } from 'zustand';
import { useHud } from './hudStore';
import type { OsintData, OsintKind } from './types';

/** Quanto o arco até o alvo fica no globo. */
export const OSINT_LINK_MS = 14_000;
const MAX_RESULTS = 12;

export const OSINT_KINDS: { id: OsintKind; label: string; example: string; hint: string }[] = [
  { id: 'ip', label: 'IP', example: '8.8.8.8', hint: 'Lugar aproximado, provedor e rede' },
  { id: 'domain', label: 'Domínio', example: 'github.com', hint: 'DNS, registro, certificado e subdomínios' },
  { id: 'url', label: 'Link', example: 'https://bit.ly/exemplo', hint: 'Para onde leva e sinais de golpe, sem abrir' },
  { id: 'cnpj', label: 'CNPJ', example: '00.000.000/0001-91', hint: 'Cadastro público da empresa' },
  { id: 'cep', label: 'CEP', example: '01310-100', hint: 'Rua, bairro e cidade' },
  { id: 'ddd', label: 'DDD', example: '48', hint: 'Estado e cidades' },
  { id: 'email', label: 'Email', example: 'voce@exemplo.com', hint: 'Em quais vazamentos conhecidos apareceu' },
  { id: 'username', label: 'Usuário', example: 'torvalds', hint: 'Em quais sites públicos existe o perfil' },
  { id: 'network', label: 'Minha rede', example: '', hint: 'IP público, portas abertas e aparelhos na rede' },
];

export function kindLabel(kind: OsintKind): string {
  return OSINT_KINDS.find((item) => item.id === kind)?.label ?? kind;
}

const IPV4 = /^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$/;
const IPV6 = /^[0-9a-f:]+:[0-9a-f:.]*$/i;
const EMAIL = /^[a-z0-9._%+-]{1,64}@(?:[a-z0-9-]+\.)+[a-z]{2,}$/i;
const DOMAIN = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$/i;
const USERNAME = /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,37}[A-Za-z0-9])?$/;

/** CPF ou telefone: o que este protocolo não consulta (o servidor recusa do mesmo jeito). */
export function looksPersonal(text: string): boolean {
  const value = text.trim();
  const digits = value.replace(/\D/g, '');
  if (/^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$/.test(value) && digits.length === 11) return true;
  return /^\+?(?:55)?\s*\(?\d{2}\)?\s*9?\d{4}[-\s]?\d{4}$/.test(value) && digits.length >= 10;
}

/** A consulta que combina com o texto, ou null (mesma ordem do osint.detect_kind). */
export function guessKind(text: string): OsintKind | null {
  const value = text.trim();
  if (!value) return null;
  const bare = value.replace(/^\[|\]$/g, '');
  if (IPV4.test(bare) || (bare.includes(':') && !bare.includes('/') && IPV6.test(bare))) return 'ip';
  if (value.includes('@') && EMAIL.test(value)) return 'email';
  if (/^[\d.\-/\s()]+$/.test(value)) {
    const digits = value.replace(/\D/g, '');
    if (digits.length === 14) return 'cnpj';
    if (digits.length === 8) return 'cep';
    if (digits.length === 2) return 'ddd';
    return null;
  }
  const lowered = value.toLowerCase();
  if (lowered.includes('://') || (lowered.includes('/') && lowered.split('/')[0].includes('.'))) return 'url';
  if (lowered.includes('.') && !/\s/.test(lowered)) return DOMAIN.test(lowered.replace(/^www\./, '')) ? 'domain' : null;
  return USERNAME.test(value.replace(/^@/, '')) ? 'username' : null;
}

/** SHA-1 em hexadecimal maiúsculo, calculado no navegador. */
export async function sha1Hex(text: string, subtle: Pick<SubtleCrypto, 'digest'> = crypto.subtle): Promise<string> {
  const digest = await subtle.digest('SHA-1', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('').toUpperCase();
}

/** Quantas vezes o hash aparece entre os sufixos devolvidos para o prefixo dele (0: não vazou). */
export function pwnedCount(hash: string, suffixes: [string, number][]): number {
  const suffix = hash.slice(5).toUpperCase();
  return suffixes.find(([candidate]) => candidate.toUpperCase() === suffix)?.[1] ?? 0;
}

/**
 * Confere uma senha em vazamentos conhecidos por k-anonimato: só os 5 primeiros caracteres do
 * SHA-1 saem do navegador; a comparação com o resto do hash é feita aqui.
 */
export async function checkPassword(password: string, fetcher: typeof fetch = fetch): Promise<number> {
  const hash = await sha1Hex(password);
  const response = await fetcher(`/api/osint/pwned/${hash.slice(0, 5)}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(await errorDetail(response));
  const body = (await response.json()) as { suffixes?: [string, number][] };
  return pwnedCount(hash, body.suffixes ?? []);
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    // Sem corpo JSON: fica a mensagem genérica.
  }
  return `A consulta falhou (${response.status}).`;
}

interface OsintState {
  results: OsintData[];
  pending: boolean;
  error: string | null;
  /** Consulta pelo servidor; `kind` null deixa o servidor reconhecer pelo formato. */
  run: (target: string, kind?: OsintKind | null) => Promise<void>;
  remove: (ts: number) => void;
  clear: () => void;
}

export const useOsint = create<OsintState>((set, get) => ({
  results: [],
  pending: false,
  error: null,
  run: async (target, kind = null) => {
    if (get().pending) return;
    set({ pending: true, error: null });
    try {
      const response = await fetch('/api/osint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, target }),
      });
      if (!response.ok) throw new Error(await errorDetail(response));
      const result = (await response.json()) as OsintData;
      const hud = useHud.getState();
      if (result.point) hud.addGeoLinks([{ ...result.point, host: result.title }], 'source', OSINT_LINK_MS);
      hud.addLog('ok', `Olho de Deus: ${result.label} · ${result.title}`);
      set((s) => ({
        pending: false,
        // A mesma consulta refeita sobe para o topo em vez de duplicar.
        results: [result, ...s.results.filter((item) => !(item.kind === result.kind && item.target === result.target))].slice(0, MAX_RESULTS),
      }));
    } catch (error) {
      set({ pending: false, error: error instanceof Error && error.message ? error.message : 'A consulta falhou.' });
    }
  },
  remove: (ts) => set((s) => ({ results: s.results.filter((item) => item.ts !== ts) })),
  clear: () => set({ results: [], error: null }),
}));
