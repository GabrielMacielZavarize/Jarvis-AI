import { useEffect, useRef, useSyncExternalStore } from 'react';
import { usePrefs } from '../lib/prefs';
import { startHum } from '../lib/reactorHum';
import { getSoundSettings, subscribeSoundSettings } from '../lib/sounds';

/** Runs the reactor hum while Ajustes has it on and the interface sounds are on. */
export function useReactorHum(active: boolean) {
  const { reactorHum } = usePrefs();
  const sounds = useSyncExternalStore(subscribeSoundSettings, getSoundSettings);
  const on = active && reactorHum && sounds.enabled && sounds.volume > 0;
  const hum = useRef<ReturnType<typeof startHum>>(null);

  useEffect(() => {
    if (!on) return;
    hum.current = startHum(getSoundSettings().volume);
    return () => {
      hum.current?.stop();
      hum.current = null;
    };
  }, [on]);

  useEffect(() => {
    hum.current?.setVolume(sounds.volume);
  }, [sounds.volume]);
}
