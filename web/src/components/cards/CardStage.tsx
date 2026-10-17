import { AnimatePresence, motion } from 'motion/react';
import type { ReactNode } from 'react';
import { useHud } from '../../lib/hudStore';
import type { HudCard } from '../../lib/types';
import { ProtocolsPanel } from '../ProtocolsPanel';
import { DiagnosticsBody, EmailBody, NewsBody, NoteBody, SearchBody, TimeBody, TimerBody, WeatherBody } from './Cards';
import { HoloCard } from './HoloCard';

function describe(card: HudCard): { code: string; title: string; body: ReactNode } {
  switch (card.kind) {
    case 'weather':
      return { code: 'WX-01', title: 'Meteorologia', body: <WeatherBody data={card.data} /> };
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
      return { code: 'COM-08', title: 'Email', body: <EmailBody data={card.data} /> };
  }
}

export function CardStage({ enabledTools }: { enabledTools: string[] | null }) {
  const cards = useHud((s) => s.cards);
  const dismiss = useHud((s) => s.dismissCard);

  return (
    <div className="stage">
      <AnimatePresence mode="popLayout" initial={false}>
        {cards.length === 0 ? (
          <motion.div key="protocols" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <ProtocolsPanel enabled={enabledTools} />
          </motion.div>
        ) : (
          cards.map((card) => {
            const { code, title, body } = describe(card);
            return (
              <HoloCard key={card.id} code={code} title={title} onClose={() => dismiss(card.id)}>
                {body}
              </HoloCard>
            );
          })
        )}
      </AnimatePresence>
    </div>
  );
}
