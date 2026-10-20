import { describe, expect, it } from 'vitest';
import { inPersona, isTheme, sceneLook, THEMES, themeInfo } from './themes';

describe('personas', () => {
  it('each one is a whole identity, not only a palette', () => {
    const shells = new Set(THEMES.map((theme) => theme.scene.shell));
    const rings = new Set(THEMES.map((theme) => theme.scene.rings));
    expect(shells.size).toBe(THEMES.length);
    expect(rings.size).toBe(THEMES.length);
    for (const theme of THEMES) {
      expect(theme.brand).toBeTruthy();
      expect(theme.speaker).toBeTruthy();
      expect(theme.boot.steps.length).toBeGreaterThan(0);
      expect(theme.sound.pitch).toBeGreaterThan(0);
    }
    expect(new Set(THEMES.map((theme) => theme.sound.pitch)).size).toBe(THEMES.length);
  });

  it('F.R.I.D.A.Y. speaks for herself and calls the user chefe', () => {
    const friday = themeInfo('friday');
    expect(friday.speaker).toBe('F.R.I.D.A.Y.');
    expect(inPersona('Boa noite, senhor. Senhor, tudo pronto.', 'friday')).toBe('Boa noite, chefe. Chefe, tudo pronto.');
    expect(inPersona('Boa noite, senhor.', 'jarvis')).toBe('Boa noite, senhor.');
    // "senhora" or "senhorio" are other words.
    expect(inPersona('A senhora do senhorio', 'friday')).toBe('A senhora do senhorio');
  });

  it('falls back to J.A.R.V.I.S. for unknown ids and keeps failure red everywhere', () => {
    expect(isTheme('ultron')).toBe(false);
    expect(themeInfo('ultron' as never).id).toBe('jarvis');
    for (const theme of THEMES) expect(sceneLook(theme.id, 'error')).toBeNull();
    expect(sceneLook('mark3', 'standby')?.primary).toBe('#ffb43c');
  });
});
