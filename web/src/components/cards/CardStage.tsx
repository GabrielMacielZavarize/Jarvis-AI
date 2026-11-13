import { AnimatePresence } from 'motion/react';
import * as m from 'motion/react-m';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useHud } from '../../lib/hudStore';
import { PANEL_META, panelTitle } from '../../lib/panels';
import type { HudCard } from '../../lib/types';
import { Panel } from '../Panel';
import { CardBody } from './CardBody';
import { HoloCard } from './HoloCard';

/** Code and title come from PANEL_META, the same names the agent gets when it lists the panels. */
function describe(card: HudCard, expanded: boolean): { code: string; title: string; body: ReactNode } {
  return { code: PANEL_META[card.kind].code, title: panelTitle(card), body: <CardBody card={card} expanded={expanded} /> };
}

/** One panel enlarged in the middle of the HUD ("Jarvis, amplia o clima"). */
function ExpandedCard({ card }: { card: HudCard }) {
  const setExpanded = useHud((s) => s.setExpanded);
  const dismiss = useHud((s) => s.dismissCard);
  const { code, title, body } = describe(card, true);

  return createPortal(
    <m.div
      className="expanded"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={(event) => {
        if (event.target === event.currentTarget) setExpanded(null);
      }}
    >
      <HoloCard
        code={code}
        title={title}
        expanded
        onToggleExpand={() => setExpanded(null)}
        onClose={() => dismiss(card.id)}
      >
        {body}
      </HoloCard>
    </m.div>,
    document.body,
  );
}

/** Enquanto nada foi projetado: diz o que aparece aqui e onde ficam os protocolos. */
function EmptyStage() {
  const setView = useHud((s) => s.setView);
  return (
    <Panel code="PRJ-00" title="Projeções" className="card stage__empty">
      <p>
        Clima, pesquisas, agenda, timers e o que mais o Jarvis buscar aparecem aqui, um painel por resultado. Diga “amplia” para ver um deles
        no centro e <kbd>Esc</kbd> para limpar tudo.
      </p>
      <button type="button" className="link-btn" onClick={() => setView('system')}>
        Ver o que ele sabe fazer
      </button>
    </Panel>
  );
}

export function CardStage() {
  const cards = useHud((s) => s.cards);
  const expandedId = useHud((s) => s.expandedId);
  const dismiss = useHud((s) => s.dismissCard);
  const setExpanded = useHud((s) => s.setExpanded);
  const expanded = cards.find((card) => card.id === expandedId) ?? null;
  const docked = cards.filter((card) => card.id !== expandedId);

  return (
    <div className="stage">
      <AnimatePresence mode="popLayout" initial={false}>
        {cards.length === 0 ? (
          <m.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <EmptyStage />
          </m.div>
        ) : (
          docked.map((card) => {
            const { code, title, body } = describe(card, false);
            return (
              <HoloCard
                key={card.id}
                code={code}
                title={title}
                onToggleExpand={() => setExpanded(card.id)}
                onClose={() => dismiss(card.id)}
              >
                {body}
              </HoloCard>
            );
          })
        )}
      </AnimatePresence>
      <AnimatePresence>{expanded && <ExpandedCard key={expanded.id} card={expanded} />}</AnimatePresence>
    </div>
  );
}
