import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  deviceNameGuess,
  fetchMe,
  formatCode,
  formatCountdown,
  formatSeen,
  normalizeCode,
  pairCodeFromHash,
  pairDevice,
  revokeDevice,
  sceneProfile,
} from './lan';

describe('LAN-26 pairing helpers', () => {
  it('reads the code from the QR link', () => {
    expect(pairCodeFromHash('#parear=042137')).toBe('042137');
    expect(pairCodeFromHash('#x=1&parear=042137')).toBe('042137');
    expect(pairCodeFromHash('#parear=12345')).toBeNull();
    expect(pairCodeFromHash('#parear=1234567')).toBeNull();
    expect(pairCodeFromHash('')).toBeNull();
  });

  it('keeps only six digits of what was typed or pasted', () => {
    expect(normalizeCode('123 456')).toBe('123456');
    expect(normalizeCode('12-34-56-78')).toBe('123456');
    expect(normalizeCode('abc')).toBe('');
    expect(formatCode('123456')).toBe('123 456');
    expect(formatCode('123')).toBe('123');
  });

  it('suggests a device name from the user agent', () => {
    expect(deviceNameGuess('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)')).toBe('iPhone');
    expect(deviceNameGuess('Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A) Chrome/130')).toBe('Pixel 8');
    expect(deviceNameGuess('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/130 Mobile')).toBe('Android');
    expect(deviceNameGuess('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('Celular');
  });

  it('formats last seen and the code countdown', () => {
    const now = 1_700_000_000_000;
    expect(formatSeen(now / 1000 - 10, now)).toBe('agora');
    expect(formatSeen(now / 1000 - 300, now)).toBe('há 5 min');
    expect(formatSeen(now / 1000 - 3 * 3600, now)).toBe('há 3 h');
    expect(formatSeen(now / 1000 - 5 * 86400, now)).toBe('há 5 dias');
    expect(formatCountdown(299)).toBe('4:59');
    expect(formatCountdown(-3)).toBe('0:00');
  });
});

describe('LAN-26 API calls', () => {
  afterEach(() => vi.unstubAllGlobals());

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

  it('pairs with the normalized code and reads the new state', async () => {
    const calls: [string, RequestInit | undefined][] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push([url, init]);
        return url === '/api/lan/pair'
          ? json({ paired: true })
          : json({ local: false, paired: true, device: { id: 'a1', name: 'Pixel', created_at: 1, last_seen: 1 } });
      }),
    );
    const me = await pairDevice('123 456', 'Pixel');
    expect(me.paired).toBe(true);
    expect(calls[0][0]).toBe('/api/lan/pair');
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ code: '123456', name: 'Pixel' });
    expect(calls[1][0]).toBe('/api/lan/me');
  });

  it('surfaces the server message when the code is wrong', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Código incorreto.' }, 403)));
    await expect(pairDevice('000000', 'x')).rejects.toThrow('Código incorreto.');
    await expect(fetchMe()).rejects.toThrow('Código incorreto.');
  });

  it('revokes by id with DELETE', async () => {
    const fetchMock = vi.fn(async () => json({ enabled: true, urls: [], pair_url: null, code: null, expires_in: 0, devices: [] }));
    vi.stubGlobal('fetch', fetchMock);
    const info = await revokeDevice('a b');
    expect(info.devices).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith('/api/lan/devices/a%20b', { method: 'DELETE' });
  });
});

describe('LAN-26 lighter 3D scene on phones', () => {
  it('uses the full scene on the PC monitors', () => {
    expect(sceneProfile(1920, 1080, false)).toMatchObject({ lite: false, postprocessing: 'full', sparkles: 90 });
    expect(sceneProfile(1080, 1920, false).lite).toBe(false); // monitor vertical
  });

  it('uses fewer pixels and effects on a phone', () => {
    const phone = sceneProfile(390, 844, true);
    expect(phone).toMatchObject({ lite: true, postprocessing: 'bloom' });
    expect(phone.dpr[1]).toBeLessThanOrEqual(1.25);
    expect(phone.sparkles).toBeLessThan(90);
    expect(sceneProfile(844, 390, true).lite).toBe(true); // deitado
    expect(sceneProfile(1024, 768, true).lite).toBe(true); // tablet
  });
});
