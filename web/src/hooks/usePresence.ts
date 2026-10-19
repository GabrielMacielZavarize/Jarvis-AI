import { useEffect, useState } from 'react';
import { type PresenceState, parsePresence } from '../lib/presence';

const POLL_MS = 5000;

/** PRS-25: polls /api/presence while JARVIS_PRESENCE=true (the Sistema panel shows it). */
export function usePresence(enabled: boolean): PresenceState | null {
  const [state, setState] = useState<PresenceState | null>(null);

  useEffect(() => {
    if (!enabled) {
      setState(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch('/api/presence', { cache: 'no-store' });
        const next = response.ok ? parsePresence(await response.json()) : null;
        if (!cancelled) setState(next);
      } catch {
        if (!cancelled) setState(null);
      }
    };
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled]);

  return state;
}
