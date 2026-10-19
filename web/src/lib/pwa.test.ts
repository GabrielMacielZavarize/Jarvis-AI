import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { shouldRegisterServiceWorker } from './pwa';

const publicFile = (name: string) => readFileSync(new URL(`../../public/${name}`, import.meta.url), 'utf8');

describe('LAN-26 PWA', () => {
  it('registers the service worker only on a secure built page', () => {
    expect(shouldRegisterServiceWorker({ supported: true, secure: true, dev: false })).toBe(true);
    expect(shouldRegisterServiceWorker({ supported: true, secure: false, dev: false })).toBe(false);
    expect(shouldRegisterServiceWorker({ supported: true, secure: true, dev: true })).toBe(false);
    expect(shouldRegisterServiceWorker({ supported: false, secure: true, dev: false })).toBe(false);
  });

  it('ships an installable manifest with PNG icons', () => {
    const manifest = JSON.parse(publicFile('manifest.webmanifest'));
    expect(manifest.display).toBe('standalone');
    expect(manifest.start_url).toBe('/');
    const sizes = manifest.icons.filter((icon: { type: string }) => icon.type === 'image/png').map((icon: { sizes: string }) => icon.sizes);
    expect(sizes).toEqual(expect.arrayContaining(['192x192', '512x512']));
    expect(manifest.icons.some((icon: { purpose?: string }) => icon.purpose === 'maskable')).toBe(true);
    for (const icon of manifest.icons) expect(() => readFileSync(new URL(`../../public${icon.src}`, import.meta.url))).not.toThrow();
  });

  it('the service worker never caches nor touches the API', () => {
    const sw = publicFile('sw.js');
    expect(sw).toContain("event.request.mode !== 'navigate'");
    expect(sw).not.toMatch(/caches\./);
  });

  it('index.html links the manifest and the iPhone icon', () => {
    const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8');
    expect(html).toContain('rel="manifest"');
    expect(html).toContain('apple-touch-icon');
    expect(html).toContain('viewport-fit=cover');
  });
});
