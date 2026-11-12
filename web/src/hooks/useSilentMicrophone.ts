import { useEffect, useState } from 'react';
import { levels, SIGNAL_FLOOR } from '../lib/audio';

/** True when the open microphone delivered no signal at all for a few seconds. */
export function useSilentMicrophone(active: boolean): boolean {
  const [silent, setSilent] = useState(false);
  useEffect(() => {
    if (!active) {
      setSilent(false);
      return;
    }
    let frame = 0;
    let peak = 0;
    let windowStart = performance.now();
    const tick = (now: number) => {
      peak = Math.max(peak, levels.user);
      if (now - windowStart > 6000) {
        setSilent(peak < SIGNAL_FLOOR);
        peak = 0;
        windowStart = now;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active]);
  return silent;
}
