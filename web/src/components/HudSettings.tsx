import { useHud } from '../lib/hudStore';
import { DEFAULT_LAYOUT, type HudPrefs, QUALITY_LABELS, type QualityPref, setPrefs, usePrefs } from '../lib/prefs';
import { LEVEL_LABELS } from '../lib/quality';
import { THEMES, themeInfo } from '../lib/themes';

const TOGGLES: { key: 'captions' | 'ambient' | 'reactorHum'; label: string; hint: string }[] = [
  { key: 'captions', label: 'Legenda ao vivo', hint: 'A fala do Jarvis embaixo do núcleo' },
  { key: 'ambient', label: 'Modo ambiente', hint: 'Relógio e clima grandes depois de 3 min sem link' },
  { key: 'reactorHum', label: 'Som do reator', hint: 'Zumbido baixo que acompanha a voz do Jarvis, só com o link aberto' },
];

/** Look of the HUD, inside Ajustes: theme, scene quality, caption, ambient mode, hum and layout. */
export function HudSettings() {
  const prefs = usePrefs();
  const scene = useHud((s) => s.sceneQuality);
  const sameLayout = JSON.stringify(prefs.layout) === JSON.stringify(DEFAULT_LAYOUT);

  return (
    <>
      <div className="stat stat--setting" style={{ gridColumn: '1 / -1' }}>
        <dt title="Cada protocolo muda o nome, a persona e a voz do assistente, o núcleo 3D, os painéis e os sons">Protocolo</dt>
        <dd className="themes" role="radiogroup" aria-label="Protocolo do HUD">
          {THEMES.map((theme) => (
            <button
              key={theme.id}
              type="button"
              role="radio"
              aria-checked={prefs.theme === theme.id}
              className={`theme-swatch ${prefs.theme === theme.id ? 'theme-swatch--on' : ''}`}
              title={theme.hint}
              onClick={() => setPrefs({ theme: theme.id })}
            >
              <i style={{ background: `linear-gradient(135deg, ${theme.swatch[0]} 50%, ${theme.swatch[1]} 50%)` }} />
              {theme.label}
            </button>
          ))}
          <small className="theme-hint">{themeInfo(prefs.theme).hint}</small>
        </dd>
      </div>
      <div className="stat stat--setting" style={{ gridColumn: '1 / -1' }}>
        <dt>
          <label htmlFor="quality-select">Qualidade da cena</label>
        </dt>
        <dd className="sound-controls__row">
          <select
            id="quality-select"
            className="select"
            value={prefs.quality}
            onChange={(event) => setPrefs({ quality: event.target.value as QualityPref })}
          >
            {(Object.keys(QUALITY_LABELS) as QualityPref[]).map((quality) => (
              <option key={quality} value={quality}>
                {QUALITY_LABELS[quality]}
              </option>
            ))}
          </select>
          <span className="quality-readout" title="Nível em uso e quadros por segundo medidos">
            {LEVEL_LABELS[scene.level]}
            {scene.fps !== null && ` · ${scene.fps} fps`}
          </span>
        </dd>
      </div>
      <div className="stat stat--setting toggles" style={{ gridColumn: '1 / -1' }}>
        {TOGGLES.map((toggle) => (
          <label key={toggle.key} className="toggle" title={toggle.hint}>
            <input
              type="checkbox"
              checked={prefs[toggle.key]}
              onChange={(event) => setPrefs({ [toggle.key]: event.target.checked } as Partial<HudPrefs>)}
            />
            <span>{toggle.label}</span>
          </label>
        ))}
        <button
          type="button"
          className="chip-btn"
          disabled={sameLayout}
          title="Volta os painéis para as colunas de fábrica"
          onClick={() => setPrefs({ layout: DEFAULT_LAYOUT })}
        >
          Restaurar painéis
        </button>
      </div>
    </>
  );
}
