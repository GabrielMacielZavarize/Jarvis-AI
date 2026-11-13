/**
 * Aparelhos da rede (ODD-42): a lista que o servidor guarda no rede_aparelhos.json, para dar nome a cada
 * um ou marcá-lo como conhecido. Quem lê a tabela ARP e avisa de aparelho novo é o servidor (netwatch.py).
 */
import { create } from 'zustand';
import type { NetworkDevice, NetworkDevices } from './types';

const BASE = '/api/osint/network/devices';

async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    // Sem corpo JSON: fica a mensagem genérica.
  }
  return `A consulta falhou (${response.status}).`;
}

export async function fetchDevices(fetcher: typeof fetch = fetch): Promise<NetworkDevices> {
  const response = await fetcher(BASE, { cache: 'no-store' });
  if (!response.ok) throw new Error(await detail(response));
  return (await response.json()) as NetworkDevices;
}

export async function patchDevice(mac: string, change: { name?: string; known?: boolean }, fetcher: typeof fetch = fetch): Promise<NetworkDevice> {
  const response = await fetcher(`${BASE}/${encodeURIComponent(mac)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(change),
  });
  if (!response.ok) throw new Error(await detail(response));
  return (await response.json()) as NetworkDevice;
}

export async function deleteDevice(mac: string, fetcher: typeof fetch = fetch): Promise<void> {
  const response = await fetcher(`${BASE}/${encodeURIComponent(mac)}`, { method: 'DELETE' });
  if (!response.ok) throw new Error(await detail(response));
}

/** O que identifica o aparelho na lista: o nome que você deu, ou o IP. */
export function deviceTitle(device: Pick<NetworkDevice, 'name' | 'ip' | 'mac'>): string {
  return device.name || device.ip || device.mac;
}

/** Quanto tempo falta para o Jarvis terminar de aprender a rede, em minutos (0 se já terminou). */
export function learningMinutes(until: string | null, now: number = Date.now()): number {
  if (!until) return 0;
  const left = Date.parse(until) - now;
  return Number.isFinite(left) && left > 0 ? Math.ceil(left / 60_000) : 0;
}

interface NetworkState {
  data: NetworkDevices | null;
  error: string | null;
  busy: boolean;
  load: () => Promise<void>;
  rename: (mac: string, name: string) => Promise<void>;
  setKnown: (mac: string, known: boolean) => Promise<void>;
  forget: (mac: string) => Promise<void>;
}

export const useNetworkDevices = create<NetworkState>((set, get) => {
  const act = async (work: () => Promise<unknown>) => {
    if (get().busy) return;
    set({ busy: true, error: null });
    try {
      await work();
      set({ data: await fetchDevices(), busy: false });
    } catch (error) {
      set({ busy: false, error: error instanceof Error && error.message ? error.message : 'Não deu para falar com o servidor.' });
    }
  };
  return {
    data: null,
    error: null,
    busy: false,
    load: () => act(async () => undefined),
    rename: (mac, name) => act(() => patchDevice(mac, { name })),
    setKnown: (mac, known) => act(() => patchDevice(mac, { known })),
    forget: (mac) => act(() => deleteDevice(mac)),
  };
});
