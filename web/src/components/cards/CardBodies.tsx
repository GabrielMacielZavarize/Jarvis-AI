import type { HudCard } from '../../lib/types';
import { CalendarBody } from './CalendarCard';
import { CameraBody } from './CameraFeed';
import { DiaryBody } from './DiaryCard';
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
import { BriefingBody, QuotesBody, SpeedBody, TasksBody } from './DayCards';
import { OsintBody } from './OsintCard';

/** O corpo de cada painel projetado. Fica num pedaço à parte do pacote: só vem quando algo é projetado. */
export default function CardBodies({ card, expanded }: { card: HudCard; expanded: boolean }) {
  return <>{panelBody(card, expanded)}</>;
}

function panelBody(card: HudCard, expanded: boolean) {
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
    case 'calendar':
      return <CalendarBody data={card.data} />;
    case 'diary':
      return <DiaryBody id={card.id} data={card.data} />;
    case 'osint':
      return <OsintBody data={card.data} />;
    case 'tasks':
      return <TasksBody data={card.data} compact={!expanded} />;
    case 'briefing':
      return <BriefingBody data={card.data} />;
    case 'quotes':
      return <QuotesBody data={card.data} />;
    case 'speed':
      return <SpeedBody data={card.data} />;
  }
}
