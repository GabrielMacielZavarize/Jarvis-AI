import { useEffect, useMemo, useRef } from 'react';
import { useClock } from '../../hooks/useClock';
import { formatDuration, formatUptime, hostnameOf, relativeTime, weekdayShort } from '../../lib/format';
import type {
  DiagnosticsData,
  EmailData,
  MediaData,
  NewsData,
  NoteData,
  SearchData,
  TimeData,
  TimerData,
  WeatherData,
} from '../../lib/types';
import { HoloGlobe } from './HoloGlobe';
import { WeatherGlyph } from './WeatherGlyph';

export function WeatherBody({ data }: { data: WeatherData }) {
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
        <HoloGlobe latitude={data.latitude} longitude={data.longitude} />
      </div>
      {data.daily.length > 0 && (
        <div className="wx__days">
          {data.daily.slice(0, 5).map((day, index) => (
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

const EMAIL_STATUS: Record<EmailData['status'], [string, string]> = {
  draft: ['Aguardando confirmação', 'status-chip--warn'],
  sent: ['Enviado', 'status-chip--ok'],
  cancelled: ['Cancelado', 'status-chip--off'],
};

export function EmailBody({ data }: { data: EmailData }) {
  const [label, tone] = EMAIL_STATUS[data.status];
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
      {data.status === 'draft' && data.code && (
        <div className="mail__code">
          Para enviar, diga
          <b>confirmar {data.code}</b>
        </div>
      )}
    </dl>
  );
}
