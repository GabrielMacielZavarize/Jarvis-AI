import { lazy, Suspense } from 'react';
import type { HudCard } from '../../lib/types';

const loadBodies = () => import('./CardBodies');
const Bodies = lazy(loadBodies);

/**
 * Baixa o código dos painéis projetados antes da primeira projeção (o App chama quando o link abre ou
 * uma ferramenta começa a rodar). Na abertura do HUD, sem nada projetado, ele nem é pedido.
 */
export function preloadCardBodies() {
  void loadBodies();
}

/** O corpo de um painel projetado; enquanto o código chega, o painel já aparece com a moldura. */
export function CardBody({ card, expanded }: { card: HudCard; expanded: boolean }) {
  return (
    <Suspense fallback={<p className="card__loading">Projetando…</p>}>
      <Bodies card={card} expanded={expanded} />
    </Suspense>
  );
}
