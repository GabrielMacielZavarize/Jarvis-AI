import { describe, expect, it } from 'vitest';
import { highlight, languageId, languageLabel } from './highlight';

const kinds = (code: string, language: string) =>
  highlight(code, language)
    .filter((token) => token.kind !== 'plain')
    .map((token) => `${token.kind}:${token.text}`);

describe('highlight', () => {
  it('keeps the code intact', () => {
    const code = "<?php\n// busca\n$user = User::find($id) ?? null; echo \"oi {$user}\";\n/* fim */";
    expect(highlight(code, 'php').map((token) => token.text).join('')).toBe(code);
  });

  it('colours PHP variables, keywords, calls, strings and comments', () => {
    expect(kinds("// x\nif ($user === null) { return findUser('a', 42); }", 'php')).toEqual([
      'comment:// x',
      'keyword:if',
      'variable:$user',
      'keyword:null',
      'keyword:return',
      'function:findUser',
      "string:'a'",
      'number:42',
    ]);
  });

  it('knows JavaScript template strings and block comments', () => {
    expect(kinds('const a = `x ${b}`; /* c */', 'javascript')).toEqual(['keyword:const', 'string:`x ${b}`', 'comment:/* c */']);
  });

  it('reads Python triple quotes and # comments', () => {
    expect(kinds('def f():\n    """doc"""  # nota\n    return None', 'py')).toEqual([
      'keyword:def',
      'function:f',
      'string:"""doc"""',
      'comment:# nota',
      'keyword:return',
      'keyword:None',
    ]);
  });

  it('matches SQL keywords in any case', () => {
    expect(kinds("SELECT id FROM users WHERE name = 'ana' -- x", 'mysql')).toEqual([
      'keyword:SELECT',
      'keyword:FROM',
      'keyword:WHERE',
      "string:'ana'",
      'comment:-- x',
    ]);
  });

  it('does not let an unclosed string eat the following lines', () => {
    const tokens = highlight("echo 'abc\necho ok", 'php');
    expect(tokens.find((token) => token.kind === 'string')?.text).toBe("'abc");
    expect(tokens.filter((token) => token.text === 'echo' && token.kind === 'keyword')).toHaveLength(2);
  });

  it('marks HTML tags and attribute values only inside tags', () => {
    expect(kinds('<a href="x">"texto"</a><!-- c -->', 'html')).toEqual(['tag:<a', 'string:"x"', 'tag:</a', 'comment:<!-- c -->']);
  });

  it('maps language names and falls back to plain text', () => {
    expect(languageId('TypeScript')).toBe('ts');
    expect(languageId('shell')).toBe('bash');
    expect(languageId('cobol')).toBe('text');
    expect(languageLabel('cobol')).toBe('cobol');
    expect(languageLabel('php')).toBe('PHP');
    expect(highlight('qualquer coisa', 'cobol')).toEqual([{ kind: 'plain', text: 'qualquer coisa' }]);
  });
});
