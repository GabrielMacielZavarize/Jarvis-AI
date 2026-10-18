import { describe, expect, it } from 'vitest';
import { trimCards } from './hudStore';
import { matchPanels, panelDetail, panelTitle } from './panels';
import { PointerImages, withPointerImage } from './pointer';
import type { HudCard, PointerData } from './types';

const click: PointerData = {
  action_id: 'a1',
  status: 'done',
  action: 'clique',
  message: "Clique em 'Play' na tela 1.",
  target: 'botão de play',
  label: 'Play',
  log: [],
};

function card(id: string, data: Partial<PointerData> | null, createdAt: number): HudCard {
  if (data === null) return { id, kind: 'search', data: { query: id, results: [] }, createdAt };
  return { id, kind: 'pointer', data: { ...click, ...data }, createdAt };
}

describe('pointer prints', () => {
  it('attaches the print whichever arrives first, by action id', () => {
    const images = new PointerImages(() => undefined);
    expect(withPointerImage(click, images).image).toBeUndefined();
    images.remember('a1', 'blob:print-1');
    expect(withPointerImage(click, images).image).toBe('blob:print-1');
    expect(withPointerImage({ ...click, action_id: 'other' }, images).image).toBeUndefined();
  });

  it('keeps only the latest prints and revokes the old blob URLs', () => {
    const revoked: string[] = [];
    const images = new PointerImages((url) => revoked.push(url));
    for (let i = 0; i < 8; i++) images.remember(`id${i}`, `blob:${i}`);
    expect(revoked).toEqual(['blob:0', 'blob:1']);
    expect(images.get('id0')).toBeUndefined();
    expect(images.get('id7')).toBe('blob:7');
  });
});

describe('MOU-20 panel', () => {
  it('is titled and matched like the other panels', () => {
    const panel = card('p', {}, 1);
    expect(panelTitle(panel)).toBe('Mouse e teclado');
    expect(panelDetail(panel)).toBe('clique · Play');
    expect(matchPanels([panel], ['mouse']).matched).toHaveLength(1);
    expect(matchPanels([panel], ['pointer']).matched).toHaveLength(1);
  });

  it('keeps a click waiting for "confirmar clique" on screen', () => {
    const now = 100;
    const pending = card('pending', { status: 'pending', code: '482913' }, 1);
    const newer = [2, 3, 4, 5].map((n) => card(`s${n}`, null, n));
    const kept = trimCards([...newer.reverse(), pending], now);
    expect(kept.map((c) => c.id)).toContain('pending');
    expect(kept).toHaveLength(4);
  });
});
