import { MODE_LABELS } from '../lib/catalog';
import { useHud } from '../lib/hudStore';
import type { ChatLine, JarvisMode } from '../lib/types';
import { LiveCaption } from './LiveCaption';
import { ToolPlate } from './ToolPlate';

interface ControlDockProps {
  mode: JarvisMode;
  /** Conversation lines, for the live caption. */
  lines: ChatLine[];
  connected: boolean;
  busy: boolean;
  micEnabled: boolean;
  demo: boolean;
  canConnect: boolean;
  onStart: () => void;
  onStop: () => void;
  onToggleMic: () => void;
  onDemo: () => void;
  /** WAK-22 detector waiting for "Jarvis". */
  wakeListening?: boolean;
  /** Seconds before the link closes for silence. */
  closingIn?: number | null;
}

function MicIcon({ muted }: { muted: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      {muted && <path d="M4 4l16 16" />}
    </svg>
  );
}

function CinemaIcon({ on }: { on: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      {on ? (
        <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
      ) : (
        <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
      )}
      <circle cx="12" cy="12" r="2.2" />
    </svg>
  );
}

function PowerIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0" />
    </svg>
  );
}

export function ControlDock(props: ControlDockProps) {
  const { mode, lines, connected, busy, micEnabled, demo, canConnect, onStart, onStop, onToggleMic, onDemo, wakeListening, closingIn } =
    props;
  const active = connected || demo;
  const cinema = useHud((s) => s.cinema);
  const setCinema = useHud((s) => s.setCinema);

  return (
    <div className="dock">
      <div className="dock__float">
        <ToolPlate />
        <LiveCaption lines={lines} speaking={mode === 'speaking'} />
      </div>
      <div className="dock__state" aria-live="polite">
        {MODE_LABELS[mode]}
      </div>
      <div className="dock__controls">
        {active && !demo && (
          <button
            type="button"
            className={`btn btn--round ${micEnabled ? '' : 'btn--muted'}`}
            onClick={onToggleMic}
            aria-label={micEnabled ? 'Silenciar microfone' : 'Ativar microfone'}
            title={micEnabled ? 'Silenciar microfone (M)' : 'Ativar microfone (M)'}
          >
            <MicIcon muted={!micEnabled} />
          </button>
        )}

        {active ? (
          <button type="button" className="btn btn--primary btn--danger" onClick={onStop}>
            <PowerIcon /> {demo ? 'Sair da simulação' : 'Encerrar link'}
          </button>
        ) : (
          <button type="button" className="btn btn--primary" onClick={onStart} disabled={busy || !canConnect}>
            <PowerIcon /> {busy ? 'Conectando…' : 'Inicializar'}
          </button>
        )}

        {!active && (
          <button type="button" className="btn btn--ghost" onClick={onDemo} title="Explorar o HUD com dados fictícios">
            Simulação
          </button>
        )}

        <button
          type="button"
          className={`btn btn--round btn--ghost ${cinema ? 'btn--on' : ''}`}
          onClick={() => setCinema(!cinema)}
          aria-pressed={cinema}
          aria-label={cinema ? 'Sair do modo cinema' : 'Modo cinema'}
          title={cinema ? 'Mostrar os painéis (F)' : 'Modo cinema: só o núcleo e a legenda (F)'}
        >
          <CinemaIcon on={cinema} />
        </button>
      </div>
      <div className="dock__hint">
        {active && !demo && closingIn ? (
          <>Encerrando por silêncio em {closingIn} s · fale para continuar</>
        ) : active ? (
          <>
            Fale naturalmente · <kbd>M</kbd> microfone · <kbd>/</kbd> digitar · <kbd>F</kbd> cinema · <kbd>Esc</kbd> limpar painéis
          </>
        ) : canConnect && wakeListening ? (
          <>
            Diga “Jarvis”, pressione <kbd>Espaço</kbd> ou clique no núcleo para iniciar
          </>
        ) : canConnect ? (
          <>
            Pressione <kbd>Espaço</kbd> ou clique no núcleo para iniciar
          </>
        ) : (
          <>Configure o .env para conversar por voz — ou explore a simulação</>
        )}
      </div>
    </div>
  );
}
