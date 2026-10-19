import { useCallback, useEffect, useState } from 'react';
import { fetchMe, type LanMe } from '../lib/lan';

/** Revoked phones find out within this time (and drop the voice link). */
const RECHECK_MS = 15000;

export type LanAccess =
  | { state: 'loading' }
  /** Old server without LAN-26, or unreachable: behave as before. */
  | { state: 'unknown' }
  | { state: 'local' }
  | { state: 'paired'; me: LanMe }
  | { state: 'unpaired'; revoked: boolean };

/** LAN-26: is this tab the PC itself, a paired phone, or a phone that still needs the code? */
export function useLanAccess(): { access: LanAccess; refresh: () => Promise<void> } {
  const [access, setAccess] = useState<LanAccess>({ state: 'loading' });

  const refresh = useCallback(async () => {
    let me: LanMe;
    try {
      me = await fetchMe();
    } catch {
      setAccess((prev) => (prev.state === 'loading' ? { state: 'unknown' } : prev));
      return;
    }
    setAccess((prev) => {
      if (me.local) return { state: 'local' };
      if (me.paired) return { state: 'paired', me };
      return { state: 'unpaired', revoked: prev.state === 'paired' };
    });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const remote = access.state === 'paired';
  useEffect(() => {
    if (!remote) return;
    const timer = window.setInterval(() => void refresh(), RECHECK_MS);
    return () => window.clearInterval(timer);
  }, [remote, refresh]);

  return { access, refresh };
}
