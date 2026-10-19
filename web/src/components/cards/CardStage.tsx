import { AnimatePresence, motion } from 'motion/react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useHud } from '../../lib/hudStore';
import { PANEL_META, panelTitle } from '../../lib/panels';
import type { HudCard } from '../../lib/types';
import { ProtocolsPanel } from '../ProtocolsPanel';
import { CameraBody } from './CameraFeed';
import { ExplainBody } from './ExplainCard';
import {
  DiagnosticsBody,
  EmailBody,
  InstallBody,
  MediaBody,
  MemoryBody,
  NewsBody,
  NoteBody,
  PointerBody,
  RoutineBody,
  ScreenBody,
  SearchBody,
  TimeBody,
  TimerBody,
  WeatherBody,
} from './Cards';
import { HoloCard } from './HoloCard';

function panelBody(card: HudCard, expanded: boolean): ReactNode {
  switch (card.kind) {
    case 'weather':
      return <WeatherBody data={card.data} expanded={expanded} />;
    case 'search':
      return <SearchBody data={card.data} />;
    case 'news':
      return <NewsBody data={card.data} />;
    case 'time':
      return <TimeBody data={card.data} />;
    case 'diagnostics':
      return <DiagnosticsBody data={card.data} />;
    case 'timer':
      return <TimerBody data={card.data} />;
    case 'note':
      return <NoteBody data={card.data} />;
    case 'email':
      return <EmailBody data={card.data} />;
    case 'media':
      return <MediaBody data={card.data} />;
    case 'screen':
      return <ScreenBody data={card.data} />;
    case 'install':
      return <InstallBody data={card.data} />;
    case 'camera':
      return <CameraBody data={card.data} />;
    case 'pointer':
      return <PointerBody data={card.data} />;
    case 'memory':
      return <MemoryBody id={card.id} data={card.data} />;
    case 'explain':
      return <ExplainBody data={card.data} />;
    case 'routine':
      return <RoutineBody data={card.data} />;
  }
}

/** Code and title come from PANEL_META, the same names the agent gets when it lists the panels. */
function describe(card: HudCard, expanded: boolean): { code: string; title: string; body: ReactNode } {
  return { code: PANEL_META[card.kind].code, title: panelTitle(card), body: panelBody(card, expanded) };
}

/** One panel enlarged in the middle of the HUD ("Jarvis, amplia o clima"). */
function ExpandedCard({ card }: { card: HudCard }) {
  const setExpanded = useHud((s) => s.setExpanded);
  const dismiss = useHud((s) => s.dismissCard);
  const { code, title, body } = describe(card, true);

  return createPortal(
    <motion.div
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
    </motion.div>,
    document.body,
  );
}

export function CardStage({ enabledTools }: { enabledTools: string[] | null }) {
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
          <motion.div key="protocols" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <ProtocolsPanel enabled={enabledTools} />
          </motion.div>
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
