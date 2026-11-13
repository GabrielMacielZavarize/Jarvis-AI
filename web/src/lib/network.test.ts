import { describe, expect, it, vi } from 'vitest';
import { deleteDevice, deviceTitle, fetchDevices, learningMinutes, patchDevice } from './network';

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const fail = (status: number, detail: string) => ({ ok: false, status, json: async () => ({ detail }) }) as Response;

describe('aparelhos da rede', () => {
  it('lista pelo servidor, sem cache', async () => {
    const fetcher = vi.fn(async () => ok({ watching: true, devices: [], unreviewed: 0, learning: false, learning_until: null }));
    const data = await fetchDevices(fetcher as unknown as typeof fetch);
    expect(data.watching).toBe(true);
    expect(fetcher).toHaveBeenCalledWith('/api/osint/network/devices', { cache: 'no-store' });
  });

  it('manda o nome e o MAC codificado, e esquece pelo DELETE', async () => {
    const fetcher = vi.fn(async () => ok({}));
    await patchDevice('aa:bb:cc:dd:ee:ff', { name: 'TV da sala' }, fetcher as unknown as typeof fetch);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/osint/network/devices/aa%3Abb%3Acc%3Add%3Aee%3Aff');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(String(init.body))).toEqual({ name: 'TV da sala' });
    await deleteDevice('aa:bb:cc:dd:ee:ff', fetcher as unknown as typeof fetch);
    expect((fetcher.mock.calls[1] as unknown as [string, RequestInit])[1].method).toBe('DELETE');
  });

  it('mostra o motivo que o servidor deu', async () => {
    const fetcher = vi.fn(async () => fail(403, 'A consulta da rede local vem desligada.'));
    await expect(fetchDevices(fetcher as unknown as typeof fetch)).rejects.toThrow('desligada');
  });

  it('o título é o nome, ou o IP quando não há nome', () => {
    expect(deviceTitle({ name: 'TV', ip: '192.168.0.9', mac: 'aa:bb:cc:dd:ee:ff' })).toBe('TV');
    expect(deviceTitle({ name: '', ip: '192.168.0.9', mac: 'aa:bb:cc:dd:ee:ff' })).toBe('192.168.0.9');
    expect(deviceTitle({ name: '', ip: '', mac: 'aa:bb:cc:dd:ee:ff' })).toBe('aa:bb:cc:dd:ee:ff');
  });

  it('conta os minutos que faltam para terminar de aprender', () => {
    const now = Date.parse('2026-11-13T10:00:00-03:00');
    expect(learningMinutes('2026-11-13T10:12:30-03:00', now)).toBe(13);
    expect(learningMinutes('2026-11-13T09:59:00-03:00', now)).toBe(0);
    expect(learningMinutes(null, now)).toBe(0);
    expect(learningMinutes('lixo', now)).toBe(0);
  });
});
