import { useEffect, useState } from 'react';

const ACTIVITY_EVENTS = ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart'] as const;

/** True after `timeoutMs` without mouse, keyboard or touch; any of them makes it false again. */
export function useIdle(timeoutMs: number, enabled: boolean): boolean {
  const [idle, setIdle] = useState(false);

  useEffect(() => {
    setIdle(false);
    if (!enabled) return;
    let timer = window.setTimeout(() => setIdle(true), timeoutMs);
    const onActivity = () => {
      setIdle(false);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setIdle(true), timeoutMs);
    };
    ACTIVITY_EVENTS.forEach((name) => window.addEventListener(name, onActivity, { passive: true }));
    return () => {
      window.clearTimeout(timer);
      ACTIVITY_EVENTS.forEach((name) => window.removeEventListener(name, onActivity));
    };
  }, [timeoutMs, enabled]);

  return idle;
}
