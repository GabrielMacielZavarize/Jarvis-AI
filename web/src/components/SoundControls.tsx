import { useSyncExternalStore } from 'react';
import { getSoundSettings, playCue, setSoundSettings, subscribeSoundSettings } from '../lib/sounds';

/** VOZ-30: interface sounds on/off and volume, saved in this browser. */
export function SoundControls() {
  const sounds = useSyncExternalStore(subscribeSoundSettings, getSoundSettings);
  const percent = Math.round(sounds.volume * 100);

  return (
    <div className="stat stat--setting sound-controls" style={{ gridColumn: '1 / -1' }}>
      <dt>
        <label htmlFor="sound-volume">Sons da interface · VOZ-30</label>
      </dt>
      <dd className="sound-controls__row">
        <label className="toggle">
          <input
            type="checkbox"
            checked={sounds.enabled}
            onChange={(event) => setSoundSettings({ enabled: event.target.checked })}
          />
          <span>{sounds.enabled ? 'Ligados' : 'Desligados'}</span>
        </label>
        <input
          id="sound-volume"
          className="range"
          type="range"
          min={0}
          max={100}
          step={5}
          value={percent}
          disabled={!sounds.enabled}
          aria-valuetext={`${percent}%`}
          onChange={(event) => setSoundSettings({ volume: Number(event.target.value) / 100 })}
          onPointerUp={() => playCue('toolDone', { force: true })}
          onKeyUp={() => playCue('toolDone', { force: true })}
        />
        <span className="sound-controls__value">{percent}%</span>
        <button
          type="button"
          className="chip-btn"
          disabled={!sounds.enabled}
          onClick={() => playCue('confirm', { force: true })}
        >
          Testar
        </button>
      </dd>
    </div>
  );
}
