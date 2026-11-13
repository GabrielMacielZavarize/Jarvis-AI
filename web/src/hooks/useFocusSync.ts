import { useEffect } from 'react';
import { blockEnded, FOCUS_POLL_MS, useFocus } from '../lib/focus';

/**
 * FOC-47: mantém o HUD em dia com a sessão de foco do servidor. Lê ao abrir, a cada poucos segundos
 * (pega o que a voz ou a bandeja mudaram) e ao voltar para a aba; a cada segundo só confere se o bloco
 * passou do fim, para a troca aparecer na hora, sem esperar a próxima leitura.
 */
export function useFocusSync(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const sync = () => void useFocus.getState().sync();
    sync();
    const poll = window.setInterval(sync, FOCUS_POLL_MS);
    const second = window.setInterval(() => {
      const { focus } = useFocus.getState();
      if (blockEnded(focus, Date.now())) sync();
    }, 1000);
    const onVisible = () => {
      if (document.visibilityState === 'visible') sync();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(second);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled]);
}
