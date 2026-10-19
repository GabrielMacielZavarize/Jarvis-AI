/** LAN-26: o celular na rede de casa. O token fica num cookie HttpOnly que o servidor grava ao
 * parear; aqui só se troca o código e se gerenciam os aparelhos (no próprio PC). */

export const CODE_DIGITS = 6;
const PAIR_HASH = /(?:^#|&)parear=(\d{6})(?:&|$)/;

export interface LanMe {
  local: boolean;
  paired: boolean;
  device: LanDevice | null;
}

export interface LanDevice {
  id: string;
  name: string;
  created_at: number;
  last_seen: number;
}

export interface LanInfo {
  enabled: boolean;
  urls: string[];
  pair_url: string | null;
  code: string | null;
  expires_in: number;
  devices: LanDevice[];
}

/** Código que veio no link do QR (https://ip:8000/#parear=123456). */
export function pairCodeFromHash(hash: string): string | null {
  return PAIR_HASH.exec(hash)?.[1] ?? null;
}

/** Só dígitos, no máximo seis: aceita "123 456" colado da tela do PC. */
export function normalizeCode(input: string): string {
  return input.replace(/\D/g, '').slice(0, CODE_DIGITS);
}

/** "123456" → "123 456", como o PC mostra. */
export function formatCode(code: string): string {
  return code.length === CODE_DIGITS ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}

/** Nome sugerido para a lista de aparelhos do PC. */
export function deviceNameGuess(userAgent: string): string {
  if (/iPhone/i.test(userAgent)) return 'iPhone';
  if (/iPad/i.test(userAgent)) return 'iPad';
  const android = /Android[^;)]*;\s*([^;)]+?)(?:\s+Build|\))/i.exec(userAgent);
  if (android && !/^(K|wv|Mobile)$/i.test(android[1].trim())) return android[1].trim().slice(0, 40);
  if (/Android/i.test(userAgent)) return 'Android';
  return 'Celular';
}

/** "agora", "há 5 min", "há 3 h", "há 2 dias" (timestamps em segundos, como o servidor). */
export function formatSeen(seconds: number, nowMs: number = Date.now()): string {
  const diff = Math.max(0, nowMs / 1000 - seconds);
  if (diff < 90) return 'agora';
  if (diff < 3600) return `há ${Math.round(diff / 60)} min`;
  if (diff < 86400 * 2) return `há ${Math.round(diff / 3600)} h`;
  return `há ${Math.round(diff / 86400)} dias`;
}

export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Erro ${response.status}`;
    try {
      detail = ((await response.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function fetchMe(): Promise<LanMe> {
  return readJson<LanMe>(await fetch('/api/lan/me', { cache: 'no-store' }));
}

export async function pairDevice(code: string, name: string): Promise<LanMe> {
  const response = await fetch('/api/lan/pair', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: normalizeCode(code), name }),
  });
  await readJson(response);
  return fetchMe();
}

export async function fetchLanInfo(): Promise<LanInfo> {
  return readJson<LanInfo>(await fetch('/api/lan/info', { cache: 'no-store' }));
}

export async function newPairingCode(): Promise<LanInfo> {
  return readJson<LanInfo>(await fetch('/api/lan/pairing', { method: 'POST' }));
}

export async function cancelPairing(): Promise<LanInfo> {
  return readJson<LanInfo>(await fetch('/api/lan/pairing', { method: 'DELETE' }));
}

export async function revokeDevice(id: string): Promise<LanInfo> {
  return readJson<LanInfo>(await fetch(`/api/lan/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }));
}

export interface SceneProfile {
  lite: boolean;
  dpr: [number, number];
  sparkles: number;
  postprocessing: 'full' | 'bloom';
}

/** Celular (tela estreita ou toque) recebe a cena 3D mais leve: menos pixels, menos efeitos. */
export function sceneProfile(width: number, height: number, coarsePointer: boolean): SceneProfile {
  const lite = Math.min(width, height) < 760 || (coarsePointer && width < 1200);
  return lite
    ? { lite, dpr: [1, 1.25], sparkles: 30, postprocessing: 'bloom' }
    : { lite, dpr: [1, 1.75], sparkles: 90, postprocessing: 'full' };
}

export function currentSceneProfile(): SceneProfile {
  if (typeof window === 'undefined') return sceneProfile(1920, 1080, false);
  const coarse = window.matchMedia?.('(pointer: coarse)').matches ?? false;
  return sceneProfile(window.innerWidth, window.innerHeight, coarse);
}
