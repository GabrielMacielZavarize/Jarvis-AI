import { describe, expect, it } from 'vitest';
import { DEFAULT_VIEW, isView, VIEWS, viewForKey, viewInfo } from './views';

describe('áreas de trabalho', () => {
  it('começa no Painel e cada área tem uma tecla só sua', () => {
    expect(DEFAULT_VIEW).toBe('home');
    expect(VIEWS[0].id).toBe('home');
    const keys = VIEWS.map((view) => view.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toEqual(keys.map((_, index) => String(index + 1)));
  });

  it('acha a área pela tecla e ignora o resto', () => {
    expect(viewForKey('1')).toBe('home');
    expect(viewForKey(VIEWS[VIEWS.length - 1].key)).toBe(VIEWS[VIEWS.length - 1].id);
    expect(viewForKey('0')).toBeNull();
    expect(viewForKey('a')).toBeNull();
  });

  it('só aceita áreas que existem', () => {
    expect(isView('settings')).toBe(true);
    expect(isView('cozinha')).toBe(false);
    expect(isView(null)).toBe(false);
    expect(viewInfo('system').label).toBe('Sistema');
    expect(viewForKey('2')).toBe('eye');
  });
});
