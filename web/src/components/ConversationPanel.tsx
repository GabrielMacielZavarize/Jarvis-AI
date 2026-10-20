import { type FormEvent, useEffect, useRef, useState } from 'react';
import { formatClock } from '../lib/format';
import { usePrefs } from '../lib/prefs';
import { themeInfo } from '../lib/themes';
import type { ChatLine } from '../lib/types';
import { Panel } from './Panel';

interface ConversationPanelProps {
  lines: ChatLine[];
  thinking: boolean;
  canSend: boolean;
  onSend: (text: string) => Promise<void>;
}

export function ConversationPanel({ lines, thinking, canSend, onSend }: ConversationPanelProps) {
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  // Who answers depends on the protocol (F.R.I.D.A.Y. speaks for herself).
  const speaker = themeInfo(usePrefs().theme).speaker;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [lines, thinking]);

  // "/" focuses the command line from anywhere.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        event.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !canSend) return;
    setSending(true);
    try {
      await onSend(text);
      setDraft('');
    } finally {
      setSending(false);
    }
  };

  const composer = (
    <form className="composer" onSubmit={submit}>
      <input
        ref={input}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={canSend ? 'Digite um comando…  ( / )' : 'Inicie o link para enviar comandos'}
        disabled={!canSend || sending}
        aria-label="Comando de texto para o Jarvis"
        maxLength={500}
      />
      <button type="submit" disabled={!canSend || sending || !draft.trim()}>
        Enviar
      </button>
    </form>
  );

  return (
    <Panel
      code="COM-02"
      title="Transcrição"
      className="conversation"
      bodyClassName="panel__body--fill"
      extra={<span>{lines.length} msg</span>}
      footer={composer}
    >
      <div ref={scroller} className="scroller">
        {lines.length === 0 && !thinking ? (
          <div className="empty">
            <div className="empty__wave" aria-hidden>
              {Array.from({ length: 9 }, (_, index) => (
                <i key={index} style={{ animationDelay: `${index * -0.13}s` }} />
              ))}
            </div>
            <div className="empty__glyph">Canal aberto</div>
            <div>Fale com o Jarvis ou digite um comando.</div>
          </div>
        ) : (
          <div className="transcript">
            {lines.map((line) => (
              <div key={line.id} className={`line line--${line.role}`}>
                <div className="line__who">
                  {line.role === 'agent' ? speaker : 'VOCÊ'}
                  <time>{formatClock(line.ts).slice(0, 5)}</time>
                </div>
                <div className="line__text">{line.text}</div>
              </div>
            ))}
            {thinking && (
              <div className="line line--agent" aria-label={`${speaker} está processando`}>
                <div className="line__who">{speaker}</div>
                <div className="typing">
                  <i />
                  <i />
                  <i />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
