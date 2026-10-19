import { useEffect, useState } from 'react';
import { DICTATION_LINGER_MS, dictationVisible, splitTail } from '../lib/dictation';
import { useHud } from '../lib/hudStore';

/** "DITADO" badge (DIT-29) with the text coming out, on screen while Jarvis types what the user says. */
export function DictationIndicator() {
  const dictation = useHud((s) => s.dictation);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!dictation || dictation.active) return;
    // Hides itself a few seconds after the dictation ends.
    const timer = window.setTimeout(() => setNow(Date.now()), DICTATION_LINGER_MS + 50);
    return () => window.clearTimeout(timer);
  }, [dictation]);

  if (!dictation || !dictationVisible(dictation, Math.max(now, dictation.updatedAt))) return null;
  const { before, typed } = splitTail(dictation);
  const status = dictation.phase === 'warn' ? 'warn' : dictation.active ? 'on' : 'off';

  return (
    <section className={`dict-alert dict-alert--${status}`} aria-live="polite" aria-label="Modo ditado">
      <header className="dict-alert__head">
        <i className="dict-alert__dot" aria-hidden />
        <span className="dict-alert__label">{dictation.active ? 'Ditado' : 'Ditado encerrado'}</span>
        {dictation.caps && <span className="dict-alert__badge">MAIÚSCULAS</span>}
        {dictation.window && <span className="dict-alert__meta">{dictation.window}</span>}
      </header>
      <p className="dict-alert__text">
        {before || typed ? (
          <>
            {before}
            <mark>{typed}</mark>
            {dictation.active && <i className="dict-alert__caret" aria-hidden />}
          </>
        ) : (
          <span className="dict-alert__hint">Pode falar… “fim do ditado” para parar.</span>
        )}
      </p>
      {(dictation.phase === 'warn' || !dictation.active) && dictation.message && (
        <p className="dict-alert__msg">{dictation.message}</p>
      )}
      {dictation.active && dictation.commands.length > 0 && (
        <p className="dict-alert__msg">Comando: {dictation.commands.join(' · ')}</p>
      )}
    </section>
  );
}
