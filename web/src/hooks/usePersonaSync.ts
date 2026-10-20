import { useEffect, useRef } from 'react';
import { getPrefs, setPrefs, usePrefs } from '../lib/prefs';
import { isTheme } from '../lib/themes';

/**
 * Keeps the HUD protocol and the server's persona.json in step, so the agent answers with the
 * persona and voice of the theme on screen (personas.py) and every device shows the same one.
 * On load the server's choice wins; when nobody chose yet, this browser's theme goes up. Each
 * change made here (Ajustes or "Jarvis, chama a Friday") is sent to the server.
 *
 * `server` is the `persona` of /api/status: undefined while unknown (or an older server).
 */
export function usePersonaSync(server: string | null | undefined) {
  const { theme } = usePrefs();
  // What the server holds, as far as this tab knows (undefined: not read yet).
  const known = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (server === undefined || known.current !== undefined) return;
    known.current = server;
    if (isTheme(server) && server !== getPrefs().theme) setPrefs({ theme: server });
  }, [server]);

  useEffect(() => {
    // getPrefs, not the rendered theme: the effect above may have just adopted the server's.
    const current = getPrefs().theme;
    if (known.current === undefined || known.current === current) return;
    const controller = new AbortController();
    fetch('/api/persona', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona: current }),
      signal: controller.signal,
    })
      .then((response) => {
        if (response.ok) known.current = current;
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [theme, server]);
}
