import { useEffect, useState } from 'react';
import type { ServerStatus } from '../lib/types';

export type StatusResult =
  | { state: 'loading' }
  | { state: 'unreachable' }
  | { state: 'ok'; status: ServerStatus };

/** Polls /api/status until the backend reports it is ready. */
export function useServerStatus(): StatusResult {
  const [result, setResult] = useState<StatusResult>({ state: 'loading' });

  useEffect(() => {
    let cancelled = false;
    let timeout: number | undefined;

    const load = async () => {
      let ready = false;
      try {
        const response = await fetch('/api/status', { cache: 'no-store' });
        if (!response.ok) throw new Error(String(response.status));
        const status = (await response.json()) as ServerStatus;
        ready = status.ready;
        if (!cancelled) setResult({ state: 'ok', status });
      } catch {
        if (!cancelled) setResult({ state: 'unreachable' });
      }
      if (!cancelled && !ready) timeout = window.setTimeout(load, 8000);
    };

    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, []);

  return result;
}
