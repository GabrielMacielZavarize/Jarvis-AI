import { useEffect, useMemo, useRef, useState } from 'react';
import { useClock } from '../../hooks/useClock';
import { formatDuration, formatUptime, groupCode, hostnameOf, relativeTime, savedDate, weekdayShort } from '../../lib/format';
import { useHud } from '../../lib/hudStore';
import { forgetMemory, MemoryOfflineError } from '../../lib/memoryLink';
import type {
  DiagnosticsData,
  EmailData,
  InstallData,
  InstallPackage,
  MediaData,
  MemoryCategory,
  MemoryData,
  MemoryItem,
  ScreenData,
  NewsData,
  NoteData,
  SearchData,
  TimeData,
  TimerData,
  WeatherData,
} from '../../lib/types';
import { HoloGlobe } from './HoloGlobe';
import { WeatherGlyph } from './WeatherGlyph';

export function WeatherBody({ data, expanded = false }: { data: WeatherData; expanded?: boolean }) {
  const { current } = data;
  return (
    <>
      <div className="wx">
        <div>
          <div className="card__sub">
            {data.location}
            {data.country ? ` · ${data.country}` : ''}
          </div>
          <div className="wx__now">
            <WeatherGlyph code={current.code} isDay={current.is_day} />
            <div className="wx__temp">
              {Math.round(current.temperature)}
              <small>°C</small>
            </div>
          </div>
          <div className="wx__label">{current.label}</div>
          <div className="wx__facts">
            {current.feels_like != null && <span>Sensação {Math.round(current.feels_like)}°</span>}
            <span>Umid. {current.humidity}%</span>
            <span>Vento {Math.round(current.wind)} km/h</span>
          </div>
        </div>
        <HoloGlobe latitude={data.latitude} longitude={data.longitude} size={expanded ? 220 : 128} />
      </div>
      {data.daily.length > 0 && (
        <div className="wx__days">
          {data.daily.slice(0, 7).map((day, index) => (
            <div key={day.date} className="wx__day" title={day.label}>
              <span>{index === 0 ? 'HOJE' : weekdayShort(day.date)}</span>
              <WeatherGlyph code={day.code} small />
              <b>{Math.round(day.max)}°</b>
              <span>{Math.round(day.min)}°</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export function SearchBody({ data }: { data: SearchData }) {
  return (
    <>
      <div className="card__sub" style={{ marginBottom: 10 }}>
        Consulta: “{data.query}”
      </div>
      <ol className="results">
        {data.results.map((result) => (
          <li key={result.url} className="result">
            <a href={result.url} target="_blank" rel="noreferrer noopener">
              {result.title}
            </a>
            <div className="result__meta">{hostnameOf(result.url)}</div>
            <div className="result__snippet">{result.snippet}</div>
          </li>
        ))}
      </ol>
    </>
  );
}

export function NewsBody({ data }: { data: NewsData }) {
  return (
    <>
      <div className="card__sub" style={{ marginBottom: 10 }}>
        Tópico: {data.topic}
      </div>
      <ol className="results">
        {data.items.map((item) => (
          <li key={`${item.title}-${item.source}`} className="result">
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer noopener">
                {item.title}
              </a>
            ) : (
              <a role="presentation">{item.title}</a>
            )}
            <div className="result__meta">
              {item.source}
              {item.date ? ` · ${relativeTime(item.date)}` : ''}
            </div>
            {item.snippet && <div className="result__snippet">{item.snippet}</div>}
          </li>
        ))}
      </ol>
    </>
  );
}

export function TimeBody({ data }: { data: TimeData }) {
  const now = useClock(1000);
  const isLocal = data.timezone === 'local' || data.location === 'Horário local';
  const zone = isLocal ? undefined : data.timezone;
  const parts = useMemo(() => {
    try {
      return {
        time: new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: zone }).format(now),
        date: new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long', timeZone: zone }).format(now),
      };
    } catch {
      return { time: new Date(now).toLocaleTimeString('pt-BR'), date: '' };
    }
  }, [now, zone]);
  const [hh, mm, ss] = parts.time.split(':');

  return (
    <div className="time">
      <div>
        <div className="card__sub">{data.location}</div>
        <div className="time__clock">
          {hh}
          <span>:</span>
          {mm}
          <span>:</span>
          {ss}
        </div>
        <div className="time__date">{parts.date}</div>
        <div className="time__zone">
          {isLocal ? 'Fuso local' : data.timezone} · {data.utc_offset}
        </div>
      </div>
      {data.latitude != null && data.longitude != null && (
        <HoloGlobe latitude={data.latitude} longitude={data.longitude} size={112} />
      )}
    </div>
  );
}

function Gauge({ label, value, detail }: { label: string; value: number; detail: string }) {
  const radius = 34;
  const circumference = 2 * Math.PI * radius * 0.75;
  const pct = Math.max(0, Math.min(100, value));
  const tone = pct > 85 ? 'var(--c-danger)' : pct > 65 ? 'var(--c-accent)' : 'var(--c-primary)';

  return (
    <div className="gauge">
      <svg viewBox="0 0 84 84" aria-label={`${label} ${pct}%`}>
        <g transform="rotate(135 42 42)" fill="none" strokeWidth="5">
          <circle cx="42" cy="42" r={radius} stroke="rgb(var(--c-primary-rgb) / 0.12)" strokeDasharray={`${circumference} 999`} />
          <circle
            cx="42"
            cy="42"
            r={radius}
            stroke={tone}
            strokeDasharray={`${(circumference * pct) / 100} 999`}
            style={{ filter: `drop-shadow(0 0 4px ${tone})`, transition: 'stroke-dasharray 1s ease-out' }}
          />
        </g>
        <text x="42" y="47" textAnchor="middle" className="gauge__value">
          {Math.round(pct)}%
        </text>
      </svg>
      <div className="gauge__label">{label}</div>
      <div className="gauge__detail">{detail}</div>
    </div>
  );
}

export function DiagnosticsBody({ data }: { data: DiagnosticsData }) {
  return (
    <>
      <div className="card__sub" style={{ marginBottom: 8 }}>
        {data.hostname} · {data.os}
      </div>
      <div className="gauges">
        <Gauge label="CPU" value={data.cpu.percent} detail={`${data.cpu.cores} núcleos`} />
        <Gauge label="RAM" value={data.memory.percent} detail={`${data.memory.used_gb}/${data.memory.total_gb} GB`} />
        <Gauge label="DISCO" value={data.disk.percent} detail={`${data.disk.used_gb}/${data.disk.total_gb} GB`} />
      </div>
      <div className="cores" title="Carga por núcleo">
        {data.cpu.per_core.map((value, index) => (
          <i key={index} style={{ height: `${Math.max(4, value)}%` }} />
        ))}
      </div>
      {data.top && data.top.length > 0 && (
        <ol className="procs" aria-label="Processos que mais pesam">
          {data.top.map((proc) => (
            <li key={proc.name}>
              <span>{proc.name}</span>
              <b>{proc.cpu}%</b>
              <i>{proc.mem_mb >= 1024 ? `${(proc.mem_mb / 1024).toFixed(1)} GB` : `${proc.mem_mb} MB`}</i>
            </li>
          ))}
        </ol>
      )}
      <div className="diag-facts">
        <span>
          <b>UPTIME</b>
          {formatUptime(data.uptime_s)}
        </span>
        <span>
          <b>PROCESSOS</b>
          {data.processes}
        </span>
        <span>
          <b>{data.battery ? 'BATERIA' : 'FREQ.'}</b>
          {data.battery
            ? `${data.battery.percent}% ${data.battery.plugged ? '⚡' : ''}`
            : data.cpu.freq_mhz
              ? `${(data.cpu.freq_mhz / 1000).toFixed(1)} GHz`
              : '—'}
        </span>
      </div>
    </>
  );
}

function beep() {
  try {
    const ctx = new AudioContext();
    [0, 0.28, 0.56].forEach((offset) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + offset);
      gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + offset + 0.22);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + offset);
      osc.stop(ctx.currentTime + offset + 0.25);
    });
    window.setTimeout(() => void ctx.close(), 1200);
  } catch {
    // Audio is a nicety; ignore browsers that block it.
  }
}

export function TimerBody({ data }: { data: TimerData }) {
  const now = useClock(250);
  const total = data.duration_s ?? 0;
  const remaining = data.ends_at ? Math.max(0, (data.ends_at - now) / 1000) : 0;
  const done = data.status === 'done' || (data.ends_at != null && remaining <= 0);
  const progress = total > 0 ? 1 - remaining / total : 1;
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const rang = useRef(false);

  useEffect(() => {
    if (done && !rang.current) {
      rang.current = true;
      beep();
    }
  }, [done]);

  return (
    <div className={`timer ${done ? 'timer--done' : ''}`}>
      <svg viewBox="0 0 96 96" aria-hidden>
        <circle cx="48" cy="48" r={radius} fill="none" stroke="rgb(var(--c-primary-rgb) / 0.12)" strokeWidth="4" />
        <circle
          cx="48"
          cy="48"
          r={radius}
          fill="none"
          stroke={done ? 'var(--c-accent)' : 'var(--c-primary)'}
          strokeWidth="4"
          strokeDasharray={`${circumference * Math.min(1, progress)} ${circumference}`}
          transform="rotate(-90 48 48)"
          style={{ filter: 'drop-shadow(0 0 5px var(--c-primary))' }}
        />
        {Array.from({ length: 60 }, (_, i) => {
          const a = (i / 60) * Math.PI * 2;
          const inner = i % 5 === 0 ? 30 : 33;
          return (
            <line
              key={i}
              x1={48 + Math.cos(a) * inner}
              y1={48 + Math.sin(a) * inner}
              x2={48 + Math.cos(a) * 35}
              y2={48 + Math.sin(a) * 35}
              stroke="rgb(var(--c-primary-rgb) / 0.35)"
              strokeWidth="1"
            />
          );
        })}
      </svg>
      <div>
        <div className="timer__value">{done ? 'CONCLUÍDO' : formatDuration(remaining)}</div>
        <div className="timer__label">{data.label}</div>
        {total > 0 && <div className="card__sub">Duração {formatDuration(total)}</div>}
      </div>
    </div>
  );
}

export function NoteBody({ data }: { data: NoteData }) {
  const lines = data.content.split('\n').map((line) => line.trim()).filter(Boolean);
  const bullet = /^([-•*]|\d+[.)])\s+/;
  const isList = lines.length > 1 && lines.every((line) => bullet.test(line));
  const ordered = isList && /^\d/.test(lines[0]);

  if (isList) {
    const items = lines.map((line) => <li key={line}>{line.replace(bullet, '')}</li>);
    return <div className="note">{ordered ? <ol>{items}</ol> : <ul>{items}</ul>}</div>;
  }
  return <div className="note">{data.content}</div>;
}

export function MediaBody({ data }: { data: MediaData }) {
  return (
    <div className="media">
      {data.thumbnail ? (
        <a className="media__thumb" href={data.url} target="_blank" rel="noreferrer noopener">
          <img src={data.thumbnail} alt="" loading="lazy" />
          <span className="media__play" aria-hidden />
        </a>
      ) : null}
      <div className="card__sub">{data.service}</div>
      <a className="media__title" href={data.url} target="_blank" rel="noreferrer noopener">
        {data.title}
      </a>
      {data.channel && <div className="media__channel">{data.channel}</div>}
    </div>
  );
}

export function ScreenBody({ data }: { data: ScreenData }) {
  return (
    <figure className="screen">
      <a href={data.url} target="_blank" rel="noreferrer noopener" title="Abrir o print em tamanho real">
        <img src={data.url} alt={`Print: ${data.label}`} />
      </a>
      <figcaption className="card__sub">
        {data.label} · {new Date(data.takenAt).toLocaleTimeString('pt-BR')}
      </figcaption>
    </figure>
  );
}

const EMAIL_STATUS: Record<EmailData['status'], [string, string]> = {
  address: ['Confira o endereço', 'status-chip--warn'],
  draft: ['Aguardando confirmação', 'status-chip--warn'],
  sent: ['Enviado', 'status-chip--ok'],
  cancelled: ['Cancelado', 'status-chip--off'],
};

function ConfirmCode({ action, code }: { action: string; code: string }) {
  return (
    <div className="mail__code">
      {action}
      <b>{groupCode(code)}</b>
      <span className="mail__code-hint">pode falar os números de uma vez ou dígito por dígito</span>
    </div>
  );
}

export function EmailBody({ data }: { data: EmailData }) {
  const [label, tone] = EMAIL_STATUS[data.status];
  if (data.status === 'address') {
    return (
      <dl className="mail">
        <span className={`status-chip ${tone}`}>{label}</span>
        <div>
          <dt>ENDEREÇO MONTADO</dt>
          <dd className="mail__address">{data.to}</dd>
        </div>
        {data.allowed === false && (
          <div>
            <dt>FORA DA LISTA AUTORIZADA</dt>
            <dd>{data.suggestion ? `Você quis dizer ${data.suggestion}?` : 'Um email para ele seria bloqueado.'}</dd>
          </div>
        )}
      </dl>
    );
  }
  return (
    <dl className="mail">
      <span className={`status-chip ${tone}`}>{label}</span>
      <div>
        <dt>PARA</dt>
        <dd>{data.to}</dd>
      </div>
      {data.cc && (
        <div>
          <dt>CC</dt>
          <dd>{data.cc}</dd>
        </div>
      )}
      {data.subject && (
        <div>
          <dt>ASSUNTO</dt>
          <dd>{data.subject}</dd>
        </div>
      )}
      {data.preview && <div className="mail__preview">{data.preview}</div>}
      {data.status === 'draft' && data.code && <ConfirmCode action="Para enviar, diga “confirmar” e o código" code={data.code} />}
    </dl>
  );
}

const INSTALL_STATUS: Record<InstallData['status'], [string, string]> = {
  results: ['Resultados da busca', 'status-chip--off'],
  pending: ['Aguardando confirmação', 'status-chip--warn'],
  installing: ['Instalando…', 'status-chip--warn'],
  installed: ['Concluído', 'status-chip--ok'],
  failed: ['Falhou', 'status-chip--danger'],
  cancelled: ['Cancelado', 'status-chip--off'],
};

const SOURCE_LABELS: Record<InstallPackage['source'], string> = { winget: 'winget', msstore: 'Microsoft Store' };

function packageMeta(pkg: InstallPackage) {
  return [pkg.id, pkg.version ? `v${pkg.version}` : null, SOURCE_LABELS[pkg.source] ?? pkg.source]
    .filter(Boolean)
    .join(' · ');
}

export function InstallBody({ data }: { data: InstallData }) {
  const [label, tone] = INSTALL_STATUS[data.status];
  if (data.status === 'results') {
    const candidates = data.candidates ?? [];
    return (
      <>
        <div className="card__sub" style={{ marginBottom: 10 }}>
          Busca: “{data.query}” · nada instalado ainda
        </div>
        {candidates.length === 0 ? (
          <div className="card__sub">Nenhum pacote encontrado no winget nem na Microsoft Store.</div>
        ) : (
          <ol className="results">
            {candidates.map((pkg) => (
              <li key={`${pkg.source}:${pkg.id}`} className="result">
                <a role="presentation">{pkg.name}</a>
                <div className="result__meta">{packageMeta(pkg)}</div>
              </li>
            ))}
          </ol>
        )}
      </>
    );
  }

  const pkg = data.package;
  return (
    <dl className="mail">
      <span className={`status-chip ${tone}`}>{label}</span>
      {pkg && (
        <>
          <div>
            <dt>APLICATIVO</dt>
            <dd>{pkg.name}</dd>
          </div>
          <div>
            <dt>PACOTE</dt>
            <dd className="mail__address">{packageMeta(pkg)}</dd>
          </div>
        </>
      )}
      {data.message && <div className="mail__preview">{data.message}</div>}
      {data.status === 'pending' && data.code && (
        <ConfirmCode action="Para instalar, diga “confirmar instalação” e o código" code={data.code} />
      )}
    </dl>
  );
}

const MEMORY_GROUPS: { key: MemoryCategory; label: string }[] = [
  { key: 'perfil', label: 'Perfil' },
  { key: 'preferencia', label: 'Preferências' },
  { key: 'pessoas', label: 'Pessoas' },
  { key: 'trabalho', label: 'Trabalho' },
  { key: 'agenda', label: 'Agenda' },
  { key: 'outro', label: 'Outros' },
];

const MEMORY_STATUS: Record<MemoryData['status'], [string, string]> = {
  list: ['Memória de longo prazo', 'status-chip--off'],
  saved: ['Memória gravada', 'status-chip--ok'],
  forgotten: ['Esquecido', 'status-chip--off'],
  refused: ['Recusado por segurança', 'status-chip--danger'],
};

// The delete button asks "Apagar?" first; the second click within this window deletes.
const MEMORY_CONFIRM_MS = 4000;

function TrashIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden>
      <path d="M1.5 3h9M4.5 3V1.5h3V3M2.8 3l.6 7.5h5.2l.6-7.5M5 5v3.8M7 5v3.8" />
    </svg>
  );
}

/** MEM-23: what Jarvis remembers about the user, grouped by category, each with a delete button. */
export function MemoryBody({ id, data }: { id: string; data: MemoryData }) {
  const updateCard = useHud((s) => s.updateCard);
  const addLog = useHud((s) => s.addLog);
  const [armed, setArmed] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(null), MEMORY_CONFIRM_MS);
    return () => window.clearTimeout(timer);
  }, [armed]);

  const remove = async (item: MemoryItem) => {
    if (armed !== item.id) {
      setArmed(item.id);
      setError(null);
      return;
    }
    setArmed(null);
    setBusy(item.id);
    try {
      const { ok, ...next } = await forgetMemory(data, item.id);
      updateCard(id, 'memory', next);
      addLog(ok ? 'ok' : 'warn', ok ? 'Memória apagada pelo painel' : 'Essa memória já não existia');
    } catch (err) {
      setError(err instanceof MemoryOfflineError ? err.message : 'O Jarvis não respondeu; a memória continua salva.');
    } finally {
      setBusy(null);
    }
  };

  const [label, tone] = MEMORY_STATUS[data.status];
  const groups = MEMORY_GROUPS.map((group) => ({ ...group, items: data.items.filter((item) => item.category === group.key) }));
  const known = new Set(MEMORY_GROUPS.map((group) => group.key));
  groups[groups.length - 1].items.push(...data.items.filter((item) => !known.has(item.category)));
  const visible = groups.filter((group) => group.items.length > 0);
  const hidden = data.query ? 0 : data.total - data.items.length;

  return (
    <div className="mem">
      <div className="mem__head">
        <span className={`status-chip ${tone}`}>{label}</span>
        <span className="card__sub">
          {data.query ? `Busca: “${data.query}” · ` : ''}
          {data.total} {data.total === 1 ? 'item' : 'itens'}
        </span>
      </div>
      {data.message && <div className="mem__message">{data.message}</div>}
      {visible.length === 0 ? (
        <div className="mem__empty">
          {data.query ? 'Nada sobre isso na memória.' : 'Nada guardado ainda. Diga “Jarvis, lembra que…”.'}
        </div>
      ) : (
        visible.map((group) => (
          <section key={group.key} className="mem__group" aria-label={group.label}>
            <h3 className="mem__label">{group.label}</h3>
            <ul className="mem__list">
              {group.items.map((item) => {
                const confirming = armed === item.id;
                return (
                  <li key={item.id} className={`mem__item${item.id === data.highlight ? ' mem__item--new' : ''}`}>
                    <div className="mem__text">
                      <span className="mem__fact">{item.fact}</span>
                      <span className="mem__date">salvo em {savedDate(item.created_at) || '—'}</span>
                    </div>
                    <button
                      type="button"
                      className={`mem__del${confirming ? ' mem__del--armed' : ''}`}
                      disabled={busy !== null}
                      onClick={() => void remove(item)}
                      aria-label={confirming ? `Confirmar: apagar “${item.fact}”` : `Apagar “${item.fact}”`}
                      title={confirming ? 'Clique de novo para apagar' : 'Apagar esta memória'}
                    >
                      {busy === item.id ? '…' : confirming ? 'Apagar?' : <TrashIcon />}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
      {hidden > 0 && <div className="card__sub">+{hidden} mais antigas · pergunte “o que você sabe sobre…?”</div>}
      {error && (
        <div className="mem__error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
