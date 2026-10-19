/**
 * Small syntax highlighter for the code blocks of the screen assistant (TEL-31).
 * No dependency: a single-pass scanner per language that knows comments, strings, numbers,
 * keywords, variables and function calls. Good enough to read a fix at a glance.
 */

export type TokenKind = 'plain' | 'keyword' | 'string' | 'comment' | 'number' | 'function' | 'variable' | 'tag';

export interface Token {
  kind: TokenKind;
  text: string;
}

interface LanguageSpec {
  label: string;
  keywords: Set<string>;
  line: string[];
  block: [string, string][];
  quotes: string[];
  /** Variables with a sigil: $user (PHP, bash). */
  sigil?: string;
  /** Keywords match regardless of case (SQL). */
  caseless?: boolean;
  markup?: boolean;
}

const words = (text: string) => new Set(text.split(/\s+/).filter(Boolean));

const C_LIKE_BLOCK: [string, string][] = [['/*', '*/']];

const JS_KEYWORDS =
  'async await break case catch class const continue debugger default delete do else export extends false finally for ' +
  'from function if import in instanceof let new null of return static super switch this throw true try typeof undefined ' +
  'var void while yield interface type enum implements private public protected readonly as satisfies keyof';

const SPECS: Record<string, LanguageSpec> = {
  js: { label: 'JavaScript', keywords: words(JS_KEYWORDS), line: ['//'], block: C_LIKE_BLOCK, quotes: ["'", '"', '`'] },
  ts: { label: 'TypeScript', keywords: words(JS_KEYWORDS), line: ['//'], block: C_LIKE_BLOCK, quotes: ["'", '"', '`'] },
  php: {
    label: 'PHP',
    keywords: words(
      'abstract and array as break case catch class clone const continue declare default do echo else elseif empty enum ' +
      'extends false final finally fn for foreach function global if implements include include_once instanceof ' +
      'interface isset match namespace new null or print private protected public readonly require require_once return ' +
      'self parent static switch throw trait true try unset use var while yield',
    ),
    line: ['//', '#'],
    block: C_LIKE_BLOCK,
    quotes: ["'", '"'],
    sigil: '$',
    caseless: true,
  },
  python: {
    label: 'Python',
    keywords: words(
      'False None True and as assert async await break class continue def del elif else except finally for from global ' +
      'if import in is lambda nonlocal not or pass raise return try while with yield self match case',
    ),
    line: ['#'],
    block: [],
    quotes: ['"""', "'''", '"', "'"],
  },
  sql: {
    label: 'SQL',
    keywords: words(
      'select from where and or not insert into values update set delete create table alter drop index join left right ' +
      'inner outer on as group by order having limit offset distinct null is in like between primary key foreign ' +
      'references default case when then else end union all exists count sum avg min max',
    ),
    line: ['--'],
    block: C_LIKE_BLOCK,
    quotes: ["'", '"', '`'],
    caseless: true,
  },
  bash: {
    label: 'Shell',
    keywords: words('if then else elif fi for while do done case esac in function return export local echo exit cd sudo'),
    line: ['#'],
    block: [],
    quotes: ["'", '"'],
    sigil: '$',
  },
  json: { label: 'JSON', keywords: words('true false null'), line: [], block: [], quotes: ['"'] },
  css: { label: 'CSS', keywords: words('important media import from to'), line: [], block: C_LIKE_BLOCK, quotes: ["'", '"'] },
  html: { label: 'HTML', keywords: new Set(), line: [], block: [['<!--', '-->']], quotes: ['"', "'"], markup: true },
  text: { label: 'Texto', keywords: new Set(), line: [], block: [], quotes: [] },
};

const ALIASES: Record<string, string> = {
  javascript: 'js',
  jsx: 'js',
  mjs: 'js',
  node: 'js',
  typescript: 'ts',
  tsx: 'ts',
  py: 'python',
  python3: 'python',
  shell: 'bash',
  sh: 'bash',
  zsh: 'bash',
  powershell: 'bash',
  ps1: 'bash',
  console: 'bash',
  terminal: 'bash',
  mysql: 'sql',
  postgresql: 'sql',
  postgres: 'sql',
  sqlite: 'sql',
  xml: 'html',
  blade: 'html',
  vue: 'html',
  scss: 'css',
  less: 'css',
  laravel: 'php',
  '': 'text',
  plaintext: 'text',
  txt: 'text',
};

export function languageId(language: string | null | undefined): string {
  const key = (language ?? '').trim().toLowerCase();
  if (key in SPECS) return key;
  return ALIASES[key] ?? 'text';
}

export function languageLabel(language: string | null | undefined): string {
  const id = languageId(language);
  return id === 'text' && language ? language : SPECS[id].label;
}

const IDENT_START = /[A-Za-z_]/;
const IDENT = /[A-Za-z0-9_]/;
const DIGIT = /[0-9]/;

function push(tokens: Token[], kind: TokenKind, text: string): void {
  if (!text) return;
  const last = tokens[tokens.length - 1];
  if (last && last.kind === kind) last.text += text;
  else tokens.push({ kind, text });
}

function readString(code: string, start: number, quote: string): number {
  let index = start + quote.length;
  while (index < code.length) {
    if (quote.length === 1 && code[index] === '\\') {
      index += 2;
      continue;
    }
    if (code.startsWith(quote, index)) return index + quote.length;
    // Single-line quotes stop at the end of the line (an unclosed string must not eat the rest).
    if (quote.length === 1 && quote !== '`' && code[index] === '\n') return index;
    index += 1;
  }
  return code.length;
}

function highlightMarkup(code: string, spec: LanguageSpec): Token[] {
  const tokens: Token[] = [];
  const [open, close] = spec.block[0];
  let inTag = false;
  let index = 0;
  while (index < code.length) {
    if (!inTag && code.startsWith(open, index)) {
      const end = code.indexOf(close, index + open.length);
      const stop = end < 0 ? code.length : end + close.length;
      push(tokens, 'comment', code.slice(index, stop));
      index = stop;
      continue;
    }
    const tag = inTag ? null : /^<\/?[A-Za-z][\w:-]*/.exec(code.slice(index));
    if (tag) {
      push(tokens, 'tag', tag[0]);
      index += tag[0].length;
      inTag = true;
      continue;
    }
    const quote = inTag ? spec.quotes.find((q) => code.startsWith(q, index)) : undefined;
    if (quote) {
      const end = readString(code, index, quote);
      push(tokens, 'string', code.slice(index, end));
      index = end;
      continue;
    }
    if (inTag && code[index] === '>') inTag = false;
    push(tokens, 'plain', code[index]);
    index += 1;
  }
  return tokens;
}

/** Splits `code` into coloured tokens; joining every token's text gives `code` back. */
export function highlight(code: string, language: string | null | undefined): Token[] {
  const spec = SPECS[languageId(language)];
  if (spec.markup) return highlightMarkup(code, spec);
  const tokens: Token[] = [];
  let index = 0;
  while (index < code.length) {
    const char = code[index];

    const line = spec.line.find((marker) => code.startsWith(marker, index));
    if (line) {
      const end = code.indexOf('\n', index);
      const stop = end < 0 ? code.length : end;
      push(tokens, 'comment', code.slice(index, stop));
      index = stop;
      continue;
    }
    const block = spec.block.find(([open]) => code.startsWith(open, index));
    if (block) {
      const end = code.indexOf(block[1], index + block[0].length);
      const stop = end < 0 ? code.length : end + block[1].length;
      push(tokens, 'comment', code.slice(index, stop));
      index = stop;
      continue;
    }
    const quote = spec.quotes.find((q) => code.startsWith(q, index));
    if (quote) {
      const end = readString(code, index, quote);
      push(tokens, 'string', code.slice(index, end));
      index = end;
      continue;
    }
    if (spec.sigil && char === spec.sigil && IDENT_START.test(code[index + 1] ?? '')) {
      let end = index + 1;
      while (end < code.length && IDENT.test(code[end])) end += 1;
      push(tokens, 'variable', code.slice(index, end));
      index = end;
      continue;
    }
    if (DIGIT.test(char) && !IDENT.test(code[index - 1] ?? '')) {
      const match = /^(0x[0-9a-fA-F]+|\d[\d_]*(\.\d+)?([eE][+-]?\d+)?)/.exec(code.slice(index));
      const text = match ? match[0] : char;
      push(tokens, 'number', text);
      index += text.length;
      continue;
    }
    if (IDENT_START.test(char)) {
      let end = index + 1;
      while (end < code.length && IDENT.test(code[end])) end += 1;
      const word = code.slice(index, end);
      const key = spec.caseless ? word.toLowerCase() : word;
      let kind: TokenKind = 'plain';
      if (spec.keywords.has(key)) kind = 'keyword';
      else if (/^\s*\(/.test(code.slice(end, end + 8))) kind = 'function';
      push(tokens, kind, word);
      index = end;
      continue;
    }
    push(tokens, 'plain', char);
    index += 1;
  }
  return tokens;
}
