import { type FormEvent, useState } from 'react';
import { useClock } from '../../hooks/useClock';
import { formatChange, formatNumber, formatQuote, tasksSummary, useTasks } from '../../lib/day';
import { formatCountdown, phaseProgress, remainingSeconds, useFocus } from '../../lib/focus';
import type { BriefingData, QuotesData, SpeedData, SpeedRun, TasksData } from '../../lib/types';
import { WeatherGlyph } from './WeatherGlyph';

const hourFormat = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });

function RemoveIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <path d="M1 1l8 8M9 1L1 9" />
    </svg>
  );
}

/** Uma linha de entrada: o campo e o botão de adicionar. */
function AddLine({ placeholder, label, onAdd }: { placeholder: string; label: string; onAdd: (text: string) => Promise<boolean> }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    if (await onAdd(value)) setText('');
    setBusy(false);
  };
  return (
    <form className="day__add" onSubmit={submit}>
      <input value={text} onChange={(event) => setText(event.target.value)} placeholder={placeholder} aria-label={label} maxLength={200} autoComplete="off" />
      <button type="submit" className="chip-btn" disabled={busy || !text.trim()}>
        Adicionar
      </button>
    </form>
  );
}

/** Tarefas com caixa de marcar. `data` vem do painel que o Jarvis projetou; sem ele, da lista viva. */
export function TaskList({ data, editable = true, limit }: { data: TasksData; editable?: boolean; limit?: number }) {
  const { toggle, remove } = useTasks();
  const shown = limit ? data.tasks.slice(0, limit) : data.tasks;
  if (shown.length === 0) return <p className="day__empty">Nenhuma tarefa aberta. Diga “anota aí” ou escreva abaixo.</p>;
  return (
    <ul className="tasks">
      {shown.map((task) => (
        <li key={task.id} className={`task ${task.done ? 'task--done' : ''} ${task.overdue ? 'task--late' : ''}`}>
          <label>
            <input type="checkbox" checked={task.done} onChange={(event) => void toggle(task.id, event.target.checked)} />
            <span className="task__text">{task.text}</span>
          </label>
          {task.due_label && <span className="task__due">{task.due_label}</span>}
          {editable && (
            <button type="button" className="icon-btn" aria-label={`Apagar ${task.text}`} onClick={() => void remove(task.id)}>
              <RemoveIcon />
            </button>
          )}
        </li>
      ))}
      {limit && data.tasks.length > limit && <li className="day__more">e mais {data.tasks.length - limit}</li>}
    </ul>
  );
}

/** TAR-43: tarefas e notas, com um campo para escrever cada uma. */
export function TasksBody({ data, compact = false }: { data: TasksData; compact?: boolean }) {
  const live = useTasks((s) => s.data);
  const add = useTasks((s) => s.add);
  const remove = useTasks((s) => s.remove);
  const error = useTasks((s) => s.error);
  // Depois de um clique a lista viva vale mais que o painel projetado.
  const current = live ?? data;
  return (
    <div className="day">
      <div className="day__summary">{tasksSummary(current)}</div>
      <TaskList data={current} limit={compact ? 6 : undefined} />
      {!compact && <AddLine placeholder="Nova tarefa (ex.: fechar o relatório)" label="Nova tarefa" onAdd={(text) => add(text, 'task')} />}
      {(current.notes.length > 0 || !compact) && (
        <>
          <div className="osint__heading">
            Notas <span>{current.notes.length}</span>
          </div>
          {current.notes.length === 0 ? (
            <p className="day__empty">Nenhuma nota. Diga “anota aí: …”.</p>
          ) : (
            <ul className="notes">
              {current.notes.slice(0, compact ? 4 : 40).map((note) => (
                <li key={note.id}>
                  <span>{note.text}</span>
                  <button type="button" className="icon-btn" aria-label={`Apagar a nota ${note.text}`} onClick={() => void remove(note.id)}>
                    <RemoveIcon />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!compact && <AddLine placeholder="Nova nota" label="Nova nota" onAdd={(text) => add(text, 'note')} />}
        </>
      )}
      {error && (
        <div className="notice" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

/** COT-44: cada moeda em reais com a variação do dia, ou o resultado de uma conversão. */
export function QuotesBody({ data }: { data: QuotesData }) {
  const conversion = data.conversion;
  return (
    <div className="day">
      {conversion && (
        <div className="convert">
          <span>
            {formatNumber(conversion.amount, Number.isInteger(conversion.amount) ? 0 : 2)} {conversion.from}
          </span>
          <b>
            {formatNumber(conversion.result, Math.abs(conversion.result) >= 0.1 ? 2 : 6)} {conversion.to}
          </b>
          {conversion.rate !== null && (
            <small>
              1 {conversion.from} = {formatNumber(conversion.rate, conversion.rate >= 0.1 ? 4 : 8)} {conversion.to}
            </small>
          )}
        </div>
      )}
      {data.items.length > 0 && (
        <ul className="quotes">
          {data.items.map((item) => {
            const change = formatChange(item.change_pct);
            return (
              <li key={item.code}>
                <span className="quotes__code">{item.code}</span>
                <span className="quotes__name">{item.name}</span>
                <b>{formatQuote(item.value)}</b>
                <span className={`quotes__change quotes__change--${change.tone}`}>{change.text}</span>
              </li>
            );
          })}
        </ul>
      )}
      {data.items.length === 0 && !conversion && <p className="day__empty">Sem cotações agora.</p>}
    </div>
  );
}

function SpeedBars({ history }: { history: SpeedRun[] }) {
  const runs = history.filter((run) => run.down_mbps !== null).slice(-20);
  if (runs.length < 2) return null;
  const top = Math.max(...runs.map((run) => run.down_mbps ?? 0), 1);
  return (
    <div className="speed__history" role="img" aria-label={`Download das últimas ${runs.length} medições`}>
      {runs.map((run) => (
        <i key={run.at} style={{ height: `${Math.max(6, ((run.down_mbps ?? 0) / top) * 100)}%` }} title={`${hourFormat.format(new Date(run.at))} · ${run.down_mbps} Mbps`} />
      ))}
    </div>
  );
}

/** RED-45: a última medição da internet e a evolução do download. */
export function SpeedBody({ data }: { data: SpeedData }) {
  const last = data.last;
  if (!last) return <p className="day__empty">Nenhuma medição ainda. Diga “como está a minha internet?”.</p>;
  const value = (number: number | null, unit: string) =>
    number === null ? (
      <b>—</b>
    ) : (
      <b>
        {formatNumber(number, number >= 100 ? 0 : 1)} <small>{unit}</small>
      </b>
    );
  return (
    <div className="day">
      <div className="speed">
        <div>
          <span>Download</span>
          {value(last.down_mbps, 'Mbps')}
        </div>
        <div>
          <span>Upload</span>
          {value(last.up_mbps, 'Mbps')}
        </div>
        <div>
          <span>Latência</span>
          {value(last.ping_ms, 'ms')}
        </div>
      </div>
      {data.verdict && (
        <div className={`osint__verdict osint__verdict--${data.verdict.level}`}>
          <b aria-hidden>{data.verdict.level === 'ok' ? '✓' : data.verdict.level === 'warn' ? '!' : '✕'}</b> {data.verdict.label}
        </div>
      )}
      <SpeedBars history={data.history} />
      <div className="osint__sources">Medido às {hourFormat.format(new Date(last.at))} · servidores de teste da Cloudflare</div>
    </div>
  );
}

/** BRF-46: o resumo do dia que o Jarvis projeta com "como está o meu dia?". */
export function BriefingBody({ data }: { data: BriefingData }) {
  const { weather, next_event: event, tasks } = data;
  return (
    <div className="day">
      {weather && (
        <div className="tile__main">
          <WeatherGlyph code={weather.code} isDay={weather.is_day} />
          <div>
            <div className="tile__value">{Math.round(weather.temperature)}°</div>
            <div className="tile__note">
              {weather.city} · {weather.label}
              {weather.max != null && weather.min != null && ` · ${Math.round(weather.max)}° / ${Math.round(weather.min)}°`}
            </div>
          </div>
        </div>
      )}
      {event && (
        <div className="osint__row">
          <dt>Próxima reunião</dt>
          <dd>
            {hourFormat.format(new Date(event.start))} · {event.title}
          </dd>
        </div>
      )}
      {tasks && (
        <>
          <div className="osint__heading">
            Tarefas <span>{tasksSummary(tasks)}</span>
          </div>
          {tasks.items.length > 0 && (
            <ul className="osint__signals">
              {tasks.items.map((task) => (
                <li key={task.id} data-level={task.overdue ? 'danger' : undefined}>
                  {task.text}
                  {task.due_label && ` · ${task.due_label}`}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {data.reminders.length > 0 && (
        <>
          <div className="osint__heading">Lembretes</div>
          <ul className="osint__signals">
            {data.reminders.map((reminder) => (
              <li key={reminder.due_at + reminder.text}>
                {reminder.time} · {reminder.text}
              </li>
            ))}
          </ul>
        </>
      )}
      {data.quotes.length > 0 && <QuotesBody data={{ items: data.quotes, conversion: null }} />}
      {data.headlines.length > 0 && (
        <>
          <div className="osint__heading">Manchetes</div>
          <ul className="headlines">
            {data.headlines.map((item) => (
              <li key={item.title}>
                {/^https?:\/\//i.test(item.url) ? (
                  <a href={item.url} target="_blank" rel="noopener noreferrer">
                    {item.title}
                  </a>
                ) : (
                  item.title
                )}
                {item.source && <small> · {item.source}</small>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** FOC-47: o anel da contagem e os controles da sessão de foco. */
export function FocusBody() {
  const { focus, start, stop, skip } = useFocus();
  const now = useClock(focus.running ? 500 : 60_000);
  const [config, setConfig] = useState({ work: focus.work, rest: focus.rest, cycles: focus.cycles });
  const progress = phaseProgress(focus, now);
  const radius = 54;
  const length = 2 * Math.PI * radius;
  const field = (key: 'work' | 'rest' | 'cycles', label: string, max: number) => (
    <label className="focus__field">
      <span>{label}</span>
      <input
        type="number"
        min={1}
        max={max}
        value={config[key]}
        onChange={(event) => setConfig({ ...config, [key]: Number(event.target.value) })}
        aria-label={label}
      />
    </label>
  );

  return (
    <div className="focus">
      <div className={`focus__ring focus__ring--${focus.running ? focus.phase : 'idle'}`}>
        <svg viewBox="0 0 128 128" aria-hidden>
          <circle cx="64" cy="64" r={radius} className="focus__track" />
          <circle cx="64" cy="64" r={radius} className="focus__arc" strokeDasharray={length} strokeDashoffset={length * (1 - progress)} transform="rotate(-90 64 64)" />
        </svg>
        <div className="focus__time" role="timer" aria-live="off">
          <b>{focus.running ? formatCountdown(remainingSeconds(focus, now)) : formatCountdown(config.work * 60)}</b>
          <span>{focus.running ? (focus.phase === 'work' ? `Foco ${focus.cycle}/${focus.cycles}` : `Pausa ${focus.cycle}/${focus.cycles}`) : 'Pronto'}</span>
        </div>
      </div>
      <div className="focus__side">
        {focus.running ? (
          <div className="focus__actions">
            <button type="button" className="btn btn--ghost" onClick={skip}>
              Pular bloco
            </button>
            <button type="button" className="btn btn--danger" onClick={stop}>
              Encerrar
            </button>
          </div>
        ) : (
          <>
            <div className="focus__config">
              {field('work', 'Foco (min)', 180)}
              {field('rest', 'Pausa (min)', 60)}
              {field('cycles', 'Blocos', 12)}
            </div>
            <button type="button" className="btn" onClick={() => start(config)}>
              Começar o foco
            </button>
          </>
        )}
        <p className="osint__note">
          A contagem roda no HUD e continua com o link fechado. Cada troca de bloco avisa com som e notificação. Por voz: “começa um foco de 25
          minutos”.
        </p>
      </div>
    </div>
  );
}
