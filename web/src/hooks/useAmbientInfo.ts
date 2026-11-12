import { useEffect, useState } from 'react';
import { AMBIENT_REFRESH_MS, type AmbientInfo, parseAmbient } from '../lib/ambient';

/** Clima da JARVIS_HOME_CITY e a próxima reunião, pedidos ao servidor enquanto `active`. */
export function useAmbientInfo(active: boolean): AmbientInfo | null {
  const [info, setInfo] = useState<AmbientInfo | null>(null);
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch('/api/ambient', { cache: 'no-store' });
        if (response.ok && !cancelled) setInfo(parseAmbient(await response.json()));
      } catch {
        // Servidor fora do ar: o relógio sozinho ainda serve.
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), AMBIENT_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active]);
  return info;
}
