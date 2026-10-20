import { useEffect, useState } from 'react';
import { diaryClock, diaryDayLabel, diaryMatchLabel, DiaryOfflineError, forgetDiary, groupByDay } from '../../lib/diaryLink';
import { useHud } from '../../lib/hudStore';
import type { DiaryData, DiaryEntry } from '../../lib/types';

const DIARY_STATUS: Record<DiaryData['status'], [string, string]> = {
  list: ['Diário das conversas', 'status-chip--off'],
  forgotten: ['Apagado', 'status-chip--off'],
  skipped: ['Esta conversa fica de fora', 'status-chip--warn'],
};

const SECTIONS: { key: 'asked' | 'decided' | 'pending'; label: string }[] = [
  { key: 'asked', label: 'Pedido' },
  { key: 'decided', label: 'Feito' },
  { key: 'pending', label: 'Pendente' },
];

// Same two-step delete as the Memória panel: "Apagar?" and a second click within 4 s.
const CONFIRM_MS = 4000;

/** DIA-36: summaries of past conversations, grouped by day, each with a delete button. */
export function DiaryBody({ id, data }: { id: string; data: DiaryData }) {
  const updateCard = useHud((s) => s.updateCard);
  const addLog = useHud((s) => s.addLog);
  const [armed, setArmed] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(null), CONFIRM_MS);
    return () => window.clearTimeout(timer);
  }, [armed]);

  const remove = async (item: DiaryEntry) => {
    if (armed !== item.id) {
      setArmed(item.id);
      setError(null);
      return;
    }
    setArmed(null);
    setBusy(item.id);
    try {
      const { ok, ...next } = await forgetDiary(data, item.id);
      updateCard(id, 'diary', next);
      addLog(ok ? 'ok' : 'warn', ok ? 'Conversa apagada do diário pelo painel' : 'Essa conversa já não estava no diário');
    } catch (err) {
      setError(err instanceof DiaryOfflineError ? err.message : 'O Jarvis não respondeu; a conversa continua no diário.');
    } finally {
      setBusy(null);
    }
  };

  const [label, tone] = DIARY_STATUS[data.status];
  const filtered = Boolean(data.query || data.period);
  const hidden = filtered ? 0 : data.total - data.items.length;

  return (
    <div className="mem diary">
      <div className="mem__head">
        <span className={`status-chip ${tone}`}>{label}</span>
        <span className="card__sub">
          {[data.period, data.query ? `${data.search === 'semantic' ? 'pelo sentido' : 'busca'}: “${data.query}”` : null]
            .filter(Boolean)
            .join(' · ')}
          {filtered ? ' · ' : ''}
          {data.total} {data.total === 1 ? 'conversa' : 'conversas'}
        </span>
      </div>
      {data.message && <div className="mem__message">{data.message}</div>}
      {data.items.length === 0 ? (
        <div className="mem__empty">
          {filtered ? 'Nenhuma conversa no diário para isso.' : 'Nada no diário ainda. Cada conversa vira um resumo quando o link fecha.'}
        </div>
      ) : (
        groupByDay(data.items).map((group) => (
          <section key={group.date} className="mem__group" aria-label={diaryDayLabel(group.date)}>
            <h3 className="mem__label">{diaryDayLabel(group.date)}</h3>
            <ul className="mem__list">
              {group.items.map((item) => {
                const confirming = armed === item.id;
                return (
                  <li key={item.id} className="mem__item">
                    <div className="mem__text">
                      <span className="mem__fact">{item.title}</span>
                      {SECTIONS.filter((section) => item[section.key].length > 0).map((section) => (
                        <div key={section.key} className={`diary__row diary__row--${section.key}`}>
                          <span className="diary__tag">{section.label}</span>
                          <span>{item[section.key].join(' · ')}</span>
                        </div>
                      ))}
                      <span className="mem__date">
                        {diaryClock(item.started_at) || '—'}
                        {item.match && <span className={`mem__match mem__match--${item.match}`}>{diaryMatchLabel(item)}</span>}
                      </span>
                    </div>
                    <button
                      type="button"
                      className={`mem__del${confirming ? ' mem__del--armed' : ''}`}
                      disabled={busy !== null}
                      onClick={() => void remove(item)}
                      aria-label={confirming ? `Confirmar: apagar “${item.title}”` : `Apagar “${item.title}” do diário`}
                      title={confirming ? 'Clique de novo para apagar' : 'Apagar esta conversa do diário'}
                    >
                      {busy === item.id ? '…' : confirming ? 'Apagar?' : '×'}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
      {hidden > 0 && <div className="card__sub">+{hidden} mais antigas · pergunte “o que a gente fez na sexta?”</div>}
      {error && (
        <div className="mem__error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
