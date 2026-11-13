import { AnimatePresence } from 'motion/react';
import * as m from 'motion/react-m';
import { useEffect } from 'react';
import { useAmbientInfo } from '../hooks/useAmbientInfo';
import { useClock } from '../hooks/useClock';
import { burnInOffset, untilEvent } from '../lib/ambient';
import { useHud } from '../lib/hudStore';
import { WeatherGlyph } from './cards/WeatherGlyph';

const dateFormatter = new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });

/** After a few idle minutes without a link: big clock, weather and the next meeting, core at low power. */
export function AmbientMode({ active, wakeWord }: { active: boolean; wakeWord: boolean }) {
  const now = useClock(1000);
  const info = useAmbientInfo(active);
  const setAmbient = useHud((s) => s.setAmbient);

  useEffect(() => setAmbient(active), [active, setAmbient]);

  const time = new Date(now);
  const [hours, minutes] = time.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }).split(':');
  const offset = burnInOffset(now);
  const weather = info?.weather;
  const event = info?.next_event;

  return (
    <AnimatePresence>
      {active && (
        <m.div
          className="ambient"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 1.2 }}
          aria-label="Modo ambiente"
        >
          <div className="ambient__inner" style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}>
            <div className="ambient__clock">
              {hours}
              <span>:</span>
              {minutes}
            </div>
            <div className="ambient__date">{dateFormatter.format(time)}</div>
            {(weather || event) && (
              <div className="ambient__row">
                {weather && (
                  <div className="ambient__card">
                    <WeatherGlyph code={weather.code} isDay={weather.is_day} />
                    <div>
                      <div className="ambient__value">{Math.round(weather.temperature)}°</div>
                      <div className="ambient__label">
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
                )}
                {event && (
                  <div className="ambient__card">
                    <div>
                      <div className="ambient__value ambient__value--event">{untilEvent(event, now)}</div>
                      <div className="ambient__label">
                        {new Date(event.start).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })} ·{' '}
                        {event.title}
                        {event.call ? ' · videochamada' : event.location ? ` · ${event.location}` : ''}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="ambient__hint">{wakeWord ? 'Mexa o mouse ou diga “Jarvis”' : 'Mexa o mouse para voltar'}</div>
          </div>
        </m.div>
      )}
    </AnimatePresence>
  );
}
