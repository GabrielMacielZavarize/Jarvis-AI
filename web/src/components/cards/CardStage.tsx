import { AnimatePresence, motion } from 'motion/react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useHud } from '../../lib/hudStore';
import type { HudCard } from '../../lib/types';
import { ProtocolsPanel } from '../ProtocolsPanel';
import {
  DiagnosticsBody,
  EmailBody,
  InstallBody,
  MediaBody,
  NewsBody,
  NoteBody,
  ScreenBody,
  SearchBody,
  TimeBody,
  TimerBody,
  WeatherBody,
} from './Cards';
import { HoloCard } from './HoloCard';

function describe(card: HudCard, expanded: boolean): { code: string; title: string; body: ReactNode } {
  switch (card.kind) {
    case 'weather':
      return { code: 'WX-01', title: 'Meteorologia', body: <WeatherBody data={card.data} expanded={expanded} /> };
    case 'search':
      return { code: 'NET-02', title: 'Pesquisa', body: <SearchBody data={card.data} /> };
    case 'news':
      return { code: 'NWS-03', title: 'Notícias', body: <NewsBody data={card.data} /> };
    case 'time':
      return { code: 'CHR-04', title: 'Cronometria', body: <TimeBody data={card.data} /> };
    case 'diagnostics':
      return { code: 'SYS-05', title: 'Diagnóstico', body: <DiagnosticsBody data={card.data} /> };
    case 'timer':
      return { code: 'TMR-06', title: 'Timer', body: <TimerBody data={card.data} /> };
    case 'note':
      return { code: 'HUD-07', title: card.data.title, body: <NoteBody data={card.data} /> };
    case 'email':
      return { code: 'COM-12', title: 'Email', body: <EmailBody data={card.data} /> };
    case 'media':
      return { code: 'MED-08', title: 'Reprodução', body: <MediaBody data={card.data} /> };
    case 'screen':
      return { code: 'VIS-14', title: 'Leitura de tela', body: <ScreenBody data={card.data} /> };
    case 'install':
      return { code: 'APP-15', title: 'Instalação de app', body: <InstallBody data={card.data} /> };
  }
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
