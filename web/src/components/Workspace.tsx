import type { ReactNode } from 'react';
import { viewInfo, type ViewId } from '../lib/views';

/** Moldura das áreas que abrem por cima do núcleo: título, o que ela mostra e os painéis em colunas. */
export function Workspace({ view, children }: { view: ViewId; children: ReactNode }) {
  const info = viewInfo(view);
  return (
    <section className="workspace" id="conteudo" tabIndex={-1} aria-label={info.label} data-view={view}>
      <header className="workspace__head">
        <h2>{info.label}</h2>
        <p>{info.hint}</p>
      </header>
      <div className="workspace__grid">{children}</div>
    </section>
  );
}
