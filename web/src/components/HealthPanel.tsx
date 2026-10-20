import { useCallback, useEffect, useState } from 'react';
import { formatSeconds } from '../lib/latency';
import {
  clearHealth,
  dayLabel,
  fetchHealth,
  HEALTH_RANGES,
  type HealthRange,
  type HealthResult,
  healthBadge,
  latencyDomain,
  latencyHeadline,
  latencySeries,
  pauseLine,
  wakeLine,
} from '../lib/health';
import { Panel } from './Panel';
import { Sparkline } from './cards/Sparkline';

/** The history changes slowly; once a minute is plenty while the panel is open. */
const REFRESH_MS = 60_000;
const RANGE_LABELS: Record<HealthRange, string> = { 1: '24 h', 7: '7 dias', 30: '30 dias' };

/** SAU-40: local history of the assistant and the .env changes it suggests. Phones only read it. */
export function HealthPanel({ local }: { local: boolean }) {
  const [days, setDays] = useState<HealthRange>(7);
  const [result, setResult] = useState<HealthResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setResult(await fetchHealth(days));
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Falha ao falar com o servidor.');
    }
  }, [days]);

  useEffect(() => {
    void load();
    if (!open) return;
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load, open]);

  const clear = async () => {
    if (!window.confirm('Apagar todo o histórico do painel de saúde?')) return;
    try {
      await clearHealth();
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Falha ao limpar.');
    }
  };

  const summary = result?.enabled ? result : null;
  const suggestions = summary?.suggestions ?? [];

  return (
    <Panel
      code="SAU-40"
      title="Saúde"
      className="health"
      extra={
        <>
          <span>{healthBadge(result)}</span>
          <button type="button" className="chip-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? 'Recolher' : 'Detalhes'}
          </button>
        </>
      }
    >
      {error && <div className="notice">{error}</div>}
      {result && !result.enabled && (
        <p className="health__empty">Desligado no .env (JARVIS_HEALTH=false).</p>
      )}
      {suggestions.length > 0 && (
        <ul className="health__hints">
          {(open ? suggestions : suggestions.slice(0, 1)).map((hint) => (
            <li key={hint.text} className={`health__hint health__hint--${hint.level}`}>
              {hint.text}
            </li>
          ))}
        </ul>
      )}
      {summary && open && <HealthDetails summary={summary} />}
      {open && summary && (
        <div className="health__foot">
          {HEALTH_RANGES.map((range) => (
            <button
              key={range}
              type="button"
              className={`chip-btn ${range === days ? 'chip-btn--on' : ''}`}
              onClick={() => setDays(range)}
              aria-pressed={range === days}
            >
              {RANGE_LABELS[range]}
            </button>
          ))}
          {local && (
            <button type="button" className="chip-btn health__clear" onClick={() => void clear()}>
              Limpar
            </button>
          )}
        </div>
      )}
    </Panel>
  );
}

function HealthDetails({ summary }: { summary: Extract<HealthResult, { enabled: true }> }) {
  if (summary.events === 0) {
    return <p className="health__empty">Ainda sem dados. Converse com o Jarvis e volte aqui.</p>;
  }
  const series = latencySeries(summary);
  const headline = latencyHeadline(summary);

  return (
    <dl className="stats health__stats">
      {series.values.length > 0 && (
        <div className="stat" style={{ gridColumn: '1 / -1' }}>
          <dt title="Mediana por dia, do fim da sua fala até a primeira palavra do Jarvis">Tempo de resposta</dt>
          <dd>{headline ?? '—'}</dd>
          <Sparkline
            values={series.values}
            domain={latencyDomain(series.values)}
            height={48}
            label="Mediana diária do tempo de resposta"
            describe={(index) => `${dayLabel(series.days[index])} · ${formatSeconds(series.values[index])} · ${series.counts[index]} turnos`}
            ticks={[
              { index: 0, text: dayLabel(series.days[0]) },
              { index: series.days.length - 1, text: dayLabel(series.days[series.days.length - 1]) },
            ]}
          />
        </div>
      )}
      {summary.wake.map((item) => {
        const line = wakeLine(item);
        return (
          <div key={item.word} className="stat" style={{ gridColumn: '1 / -1' }}>
            <dt>{line.label}</dt>
            <dd className={line.alert ? 'health__alert' : undefined}>{line.detail}</dd>
          </div>
        );
      })}
      {summary.tools.length > 0 && (
        <div className="stat" style={{ gridColumn: '1 / -1' }}>
          <dt>Ferramentas com erro</dt>
          <dd>
            {summary.tools.slice(0, 4).map((tool) => (
              <div key={tool.name} title={tool.last ?? undefined}>
                {tool.name} · {tool.errors}x
              </div>
            ))}
          </dd>
        </div>
      )}
      {(summary.models.pauses.length > 0 || summary.models.switches > 0) && (
        <div className="stat" style={{ gridColumn: '1 / -1' }}>
          <dt>Modelos · {summary.models.switches} trocas</dt>
          <dd>
            {summary.models.pauses.slice(0, 4).map((pause) => (
              <div key={`${pause.model}-${pause.reason}`}>{pauseLine(pause)}</div>
            ))}
          </dd>
        </div>
      )}
      {summary.memory.searches > 0 && (
        <div className="stat" style={{ gridColumn: '1 / -1' }}>
          <dt title="JARVIS_MEMORY_MIN_SIMILARITY">Memória pelo sentido</dt>
          <dd>
            {summary.memory.searches} buscas · {summary.memory.empty} sem resultado
            {summary.memory.average !== null && ` · nota média ${summary.memory.average.toFixed(2)}`}
          </dd>
        </div>
      )}
    </dl>
  );
}
