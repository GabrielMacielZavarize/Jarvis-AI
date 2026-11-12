import type { OsintData, OsintList } from '../../lib/types';
import { HoloGlobe } from './HoloGlobe';

const VERDICT_MARK = { ok: '✓', warn: '!', danger: '✕' } as const;

/** Só http(s) vira link clicável: o texto vem de fora. */
function safeLink(url: string | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}

function ListBlock({ list }: { list: OsintList }) {
  const more = list.total - list.items.length;
  return (
    <div className="osint__list">
      <div className="osint__heading">
        {list.title} <span>{list.total}</span>
      </div>
      <ul className={list.levels ? 'osint__signals' : 'osint__items'}>
        {list.items.map((item, index) => {
          const link = safeLink(list.links?.[index]);
          return (
            <li key={`${index}-${item}`} data-level={list.levels?.[index]}>
              {link ? (
                <a href={link} target="_blank" rel="noopener noreferrer">
                  {item}
                </a>
              ) : (
                item
              )}
            </li>
          );
        })}
      </ul>
      {more > 0 && <div className="osint__more">e mais {more}</div>}
    </div>
  );
}

/** Resultado de uma consulta do Olho de Deus (ODD-42): o mesmo desenho para todos os tipos. */
export function OsintBody({ data }: { data: OsintData }) {
  return (
    <div className="osint">
      <div className="osint__top">
        <div className="osint__id">
          <div className="osint__kind">{data.label}</div>
          <div className="osint__title">{data.title}</div>
          <div className="osint__summary">{data.summary}</div>
          {data.verdict && (
            <div className={`osint__verdict osint__verdict--${data.verdict.level}`}>
              <b aria-hidden>{VERDICT_MARK[data.verdict.level]}</b> {data.verdict.label}
            </div>
          )}
        </div>
        {data.point && (
          <figure className="osint__globe" title={data.point.name}>
            <HoloGlobe latitude={data.point.lat} longitude={data.point.lon} size={104} />
            <figcaption>{data.point.name}</figcaption>
          </figure>
        )}
      </div>

      {data.sections.map((section) => (
        <dl key={section.title} className="osint__section">
          <div className="osint__heading">{section.title}</div>
          {section.rows.map(([label, value]) => (
            <div key={label} className="osint__row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ))}

      {data.lists.map((list) => (
        <ListBlock key={list.title} list={list} />
      ))}

      {data.notes.map((note) => (
        <p key={note} className="osint__note">
          {note}
        </p>
      ))}
      {data.sources.length > 0 && <div className="osint__sources">Fontes: {data.sources.slice(0, 6).join(', ')}{data.sources.length > 6 ? '…' : ''}</div>}
    </div>
  );
}
