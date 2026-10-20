import { useEffect, useState } from 'react';
import type { JarvisMode } from '../lib/types';
import { settleDelay } from '../lib/visualMode';

/** `mode` once it has held for its settle delay (lib/visualMode), so quick flips do not repaint the HUD. */
export function useSettledMode(mode: JarvisMode): JarvisMode {
  const [shown, setShown] = useState(mode);

  useEffect(() => {
    const delay = settleDelay(shown, mode);
    if (delay === 0) {
      if (shown !== mode) setShown(mode);
      return;
    }
    const timer = window.setTimeout(() => setShown(mode), delay);
    return () => window.clearTimeout(timer);
  }, [mode, shown]);

  return shown;
}
