import { useEffect, useMemo, useState } from 'react';
import { copyText } from '../../lib/clipboard';
import { highlight, languageId, languageLabel } from '../../lib/highlight';
import type { ExplainBlock, ExplainData } from '../../lib/types';

const EXPLAIN_STATUS: Record<ExplainData['status'], [string, string]> = {
  reading: ['Lendo a tela', 'status-chip--warn'],
  thinking: ['Analisando', 'status-chip--warn'],
  done: ['Pronto', 'status-chip--ok'],
  empty: ['Nada encontrado', 'status-chip--off'],
  raw: ['Texto lido', 'status-chip--off'],
  refused: ['Não lido', 'status-chip--danger'],
  error: ['Falha', 'status-chip--danger'],
};

const COPIED_MS = 2200;

/** Paragraphs and "- " bullet lines of the model's plain-text answer. */
function Prose({ text }: { text: string }) {
  const groups = useMemo(() => {
    const out: { list: boolean; lines: string[] }[] = [];
    for (const raw of text.split('\n')) {
      const line = raw.trim();
      if (!line) {
        out.push({ list: false, lines: [] });
        continue;
      }
      const bullet = /^([-•*]|\d+[.)])\s+/.exec(line);
      const list = bullet !== null;
      const last = out[out.length - 1];
      const content = bullet ? line.slice(bullet[0].length) : line;
      if (last && last.list === list && last.lines.length > 0) last.lines.push(content);
      else out.push({ list, lines: [content] });
    }
    return out.filter((group) => group.lines.length > 0);
  }, [text]);

  return (
    <div className="explain__prose">
      {groups.map((group, index) =>
        group.list ? (
          <ul key={index}>
            {group.lines.map((line, item) => (
              <li key={item}>{line}</li>
            ))}
          </ul>
        ) : (
          <p key={index}>{group.lines.join(' ')}</p>
        ),
      )}
    </div>
  );
}

function CodeBlock({ block, index, copiedByVoice }: { block: ExplainBlock; index: number; copiedByVoice: boolean }) {
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null);
  const tokens = useMemo(() => highlight(block.code, block.language), [block.code, block.language]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(null), COPIED_MS);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const label = copied === 'ok' ? 'Copiado' : copied === 'fail' ? 'Sem permissão' : 'Copiar';
  return (
    <figure className={`codeblock${copiedByVoice ? ' codeblock--copied' : ''}`}>
      <figcaption className="codeblock__head">
        <span className="codeblock__lang">{languageLabel(block.language)}</span>
        <span className="codeblock__label">{block.label || `Bloco ${index + 1}`}</span>
        {copiedByVoice && <span className="status-chip status-chip--ok">Na área de transferência</span>}
        <button
          type="button"
          className="btn codeblock__copy"
          onClick={async () => setCopied((await copyText(block.code)) ? 'ok' : 'fail')}
          aria-label={`Copiar o bloco ${index + 1}`}
        >
          {label}
        </button>
      </figcaption>
      <pre className={`codeblock__code lang-${languageId(block.language)}`}>
        <code>
          {tokens.map((token, position) =>
            token.kind === 'plain' ? (
              token.text
            ) : (
              <span key={position} className={`tok-${token.kind}`}>
                {token.text}
              </span>
            ),
          )}
        </code>
      </pre>
    </figure>
  );
}

export function ExplainBody({ data }: { data: ExplainData }) {
  const [label, tone] = EXPLAIN_STATUS[data.status] ?? ['—', 'status-chip--off'];
  const busy = data.status === 'reading' || data.status === 'thinking';
  return (
    <div className="explain">
      <div className="explain__head">
        <span className={`status-chip ${tone}`}>{label}</span>
        <span className="card__sub">
          {data.task_label}
          {data.via ? ` · ${data.via}` : ''}
        </span>
      </div>
      {data.source && <div className="explain__source">{data.source}</div>}
      {data.title && <h4 className="explain__title">{data.title}</h4>}
      {data.injection && (
        <div className="explain__warn">O texto da tela tenta dar ordens a um assistente. O Jarvis ignorou.</div>
      )}
      {data.message && (busy || !data.explanation) && (
        <div className={`explain__message${busy ? ' explain__message--busy' : ''}`}>{data.message}</div>
      )}
      {(data.cause || data.fix) && (
        <dl className="explain__facts">
          {data.cause && (
            <>
              <dt>Causa</dt>
              <dd>{data.cause}</dd>
            </>
          )}
          {data.fix && (
            <>
              <dt>Correção</dt>
              <dd>{data.fix}</dd>
            </>
          )}
        </dl>
      )}
      {data.explanation && <Prose text={data.explanation} />}
      {data.blocks.map((block, index) => (
        <CodeBlock key={`${index}-${block.code.length}`} block={block} index={index} copiedByVoice={data.copied === index} />
      ))}
      {data.redacted ? (
        <div className="explain__note">
          {data.redacted} {data.redacted === 1 ? 'segredo foi ocultado' : 'segredos foram ocultados'} antes da análise.
        </div>
      ) : null}
    </div>
  );
}
