import { useState } from 'react';
import { useAmbientInfo } from '../hooks/useAmbientInfo';
import { useClock } from '../hooks/useClock';
import type { StatusResult } from '../hooks/useServerStatus';
import { untilEvent } from '../lib/ambient';
import { greeting, suggestions } from '../lib/briefing';
import { useHud } from '../lib/hudStore';
import { usePrefs } from '../lib/prefs';
import { themeInfo } from '../lib/themes';
import { Panel } from './Panel';
import { WeatherGlyph } from './cards/WeatherGlyph';

const dateFormatter = new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });
const hourFormatter = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });

interface BriefingPanelProps {
  status: StatusResult;
  /** Link aberto com o agente (não a simulação): as sugestões viram comandos de texto. */
  canSend: boolean;
  demo: boolean;
  onSend: (text: string) => void;
  /** O detector da palavra de ativação está esperando o "Jarvis". */
  wakeListening: boolean;
  /** O microfone aberto não entrega som. */
  micSilent: boolean;
}

/**
 * O que importa agora, no topo do Painel: a saudação, o clima da cidade, a próxima reunião, o que
 * pede atenção (configuração, servidor, microfone) e três coisas para pedir ao Jarvis.
 */
export function BriefingPanel({ status, canSend, demo, onSend, wakeListening, micSilent }: BriefingPanelProps) {
  const now = useClock(30_000);
  const server = status.state === 'ok' ? status.status : null;
  const info = useAmbientInfo(server !== null);
  const address = themeInfo(usePrefs().theme).address;
  const setView = useHud((s) => s.setView);
  const today = new Date(now);
  const weather = info?.weather ?? null;
  const event = info?.next_event ?? null;
  const ideas = suggestions(server?.tools ?? null, today);
  // Com projeções na tela o briefing encolhe para uma linha e deixa o espaço para elas; o botão
  // do cabeçalho vale mais que essa regra até a próxima vez que a tela esvaziar ou encher.
  const hasCards = useHud((s) => s.cards.length > 0);
  const [choice, setChoice] = useState<{ open: boolean; withCards: boolean } | null>(null);
  const open = choice && choice.withCards === hasCards ? choice.open : !hasCards;
  const toggle = (
    <>
      <span>{hourFormatter.format(today)}</span>
      <button
        type="button"
        className="icon-btn"
        aria-expanded={open}
        aria-label={open ? 'Recolher o briefing' : 'Abrir o briefing'}
        onClick={() => setChoice({ open: !open, withCards: hasCards })}
      >
        <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
          <path d={open ? 'M2 8l4-4 4 4' : 'M2 4l4 4 4-4'} />
        </svg>
      </button>
    </>
  );

  if (!open) {
    return (
      <Panel code="BRF-00" title="Briefing" className="briefing briefing--compact" extra={toggle}>
        <p className="briefing__line">
          {weather && (
            <span>
              <b>{Math.round(weather.temperature)}°</b> {weather.city} · {weather.label}
            </span>
          )}
          {event && (
            <span>
              <b>{event.title}</b> {untilEvent(event, now)}
            </span>
          )}
          {!weather && !event && <span>{dateFormatter.format(today)}</span>}
        </p>
      </Panel>
    );
  }

  return (
    <Panel code="BRF-00" title="Briefing" className="briefing" extra={toggle}>
      <p className="briefing__hello">
        {greeting(today)}, <b>{address}</b>.
      </p>
      <p className="briefing__date">{dateFormatter.format(today)}</p>

      <div className="briefing__tiles">
        <div className="tile">
          <div className="tile__label">Clima</div>
          {weather ? (
            <div className="tile__main">
              <WeatherGlyph code={weather.code} isDay={weather.is_day} />
              <div>
                <div className="tile__value">{Math.round(weather.temperature)}°</div>
                <div className="tile__note">
                  {weather.city} · {weather.label}
                  {weather.max != null && weather.min != null && (
                    <>
                      {' '}
                      · {Math.round(weather.max)}° / {Math.round(weather.min)}°
                    </>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="tile__note tile__note--empty">
              {server?.home ? 'Buscando a previsão…' : server ? 'Defina JARVIS_HOME_CITY no .env para ver o clima aqui.' : 'Sem servidor, sem previsão.'}
            </div>
          )}
        </div>
        <div className="tile">
          <div className="tile__label">Agenda</div>
          {event ? (
            <div>
              <div className="tile__value tile__value--event">{untilEvent(event, now)}</div>
              <div className="tile__note">
                {hourFormatter.format(new Date(event.start))} · {event.title}
                {event.call ? ' · videochamada' : event.location ? ` · ${event.location}` : ''}
              </div>
            </div>
          ) : (
            <div className="tile__note tile__note--empty">
              {!server?.calendar
                ? 'Ligue o Google Agenda (JARVIS_ENABLE_CALENDAR) para ver a próxima reunião.'
                : server.calendar.connected
                  ? 'Nada marcado nas próximas 24 horas.'
                  : 'Agenda ligada, falta o login do Google.'}
            </div>
          )}
        </div>
      </div>

      {status.state === 'unreachable' && !demo && (
        <div className="notice" role="status">
          <strong>Servidor offline.</strong> Rode <code>python jarvis.py</code> para conversar. A simulação funciona mesmo assim.
        </div>
      )}
      {server && !server.ready && !demo && (
        <div className="notice" role="status">
          <strong>Configuração pendente.</strong> {server.errors.length} {server.errors.length === 1 ? 'item falta' : 'itens faltam'} no{' '}
          <code>.env</code>.{' '}
          <button type="button" className="link-btn" onClick={() => setView('system')}>
            Ver em Sistema
          </button>
        </div>
      )}
      {micSilent && (
        <div className="notice" role="alert">
          <strong>Sem sinal do microfone.</strong> O navegador não está recebendo áudio.{' '}
          <button type="button" className="link-btn" onClick={() => setView('settings')}>
            Escolher o microfone
          </button>
        </div>
      )}

      {ideas.length > 0 && (
        <div className="briefing__ideas">
          <div className="tile__label">
            {canSend ? 'Peça agora' : wakeListening ? 'Diga “Jarvis” e peça' : 'Para pedir quando o link abrir'}
          </div>
          <ul>
            {ideas.map((idea) => (
              <li key={idea.id}>
                <button
                  type="button"
                  className="idea"
                  disabled={!canSend}
                  title={canSend ? 'Enviar ao Jarvis' : 'Inicie o link para enviar'}
                  onClick={() => onSend(idea.phrase)}
                >
                  <span className="idea__code">{idea.code}</span>
                  {idea.phrase}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
