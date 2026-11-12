import { useHud } from '../lib/hudStore';
import { VIEWS, type ViewId } from '../lib/views';

/** Ícone de cada área, no traço fino dos outros ícones do HUD. */
function ViewIcon({ id }: { id: ViewId }) {
  const paths: Record<ViewId, React.ReactNode> = {
    home: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="3" />
        <path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3" />
      </>
    ),
    system: <path d="M2 12h4l2.5-6 4 12 2.5-6h7" />,
    settings: (
      <>
        <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
        <circle cx="16" cy="7" r="2" />
        <circle cx="8" cy="17" r="2" />
      </>
    ),
  };
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {paths[id]}
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l5 5" />
    </svg>
  );
}

/**
 * As áreas de trabalho do HUD. No computador ficam no topo, entre a marca e o relógio; no celular
 * viram a barra de baixo (`variant="bar"`), ao alcance do polegar.
 */
export function NavTabs({ variant }: { variant: 'top' | 'bar' }) {
  const view = useHud((s) => s.view);
  const setView = useHud((s) => s.setView);
  const setPalette = useHud((s) => s.setPalette);

  return (
    <nav className={`nav nav--${variant}`} aria-label="Áreas do HUD">
      {VIEWS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`nav__tab ${view === item.id ? 'nav__tab--on' : ''}`}
          aria-current={view === item.id ? 'page' : undefined}
          title={`${item.hint} (${item.key})`}
          onClick={() => setView(item.id)}
        >
          <ViewIcon id={item.id} />
          <span>{item.label}</span>
        </button>
      ))}
      <button
        type="button"
        className="nav__tab nav__tab--search"
        title="Paleta de comandos (Ctrl+K)"
        aria-label="Abrir a paleta de comandos"
        onClick={() => setPalette(true)}
      >
        <SearchIcon />
        <span className="nav__kbd">
          {variant === 'top' ? (
            <>
              <kbd>Ctrl</kbd>
              <kbd>K</kbd>
            </>
          ) : (
            'Buscar'
          )}
        </span>
      </button>
    </nav>
  );
}
