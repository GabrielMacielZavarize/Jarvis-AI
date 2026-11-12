import { describe, expect, it, vi } from 'vitest';
import { checkPassword, guessKind, kindLabel, looksPersonal, OSINT_KINDS, pwnedCount, sha1Hex } from './osint';

describe('palpite da consulta', () => {
  it('reconhece cada formato', () => {
    expect(guessKind('8.8.8.8')).toBe('ip');
    expect(guessKind('2001:4860:4860::8888')).toBe('ip');
    expect(guessKind('voce@exemplo.com')).toBe('email');
    expect(guessKind('00.000.000/0001-91')).toBe('cnpj');
    expect(guessKind('01310-100')).toBe('cep');
    expect(guessKind('48')).toBe('ddd');
    expect(guessKind('https://bit.ly/abc')).toBe('url');
    expect(guessKind('loja.com.br/promo')).toBe('url');
    expect(guessKind('github.com')).toBe('domain');
    expect(guessKind('www.github.com')).toBe('domain');
    expect(guessKind('@torvalds')).toBe('username');
    expect(guessKind('torvalds')).toBe('username');
  });

  it('não chuta quando não dá para saber', () => {
    expect(guessKind('')).toBeNull();
    expect(guessKind('12345')).toBeNull();
    expect(guessKind('duas palavras')).toBeNull();
    expect(guessKind('999.999.999.999')).toBeNull();
  });

  it('CPF e telefone não viram consulta', () => {
    expect(looksPersonal('123.456.789-09')).toBe(true);
    expect(looksPersonal('12345678909')).toBe(true);
    expect(looksPersonal('(48) 99999-1234')).toBe(true);
    expect(looksPersonal('+55 48 99999-1234')).toBe(true);
    expect(guessKind('123.456.789-09')).toBeNull();
    expect(looksPersonal('00.000.000/0001-91')).toBe(false);
    expect(looksPersonal('01310-100')).toBe(false);
    expect(looksPersonal('github.com')).toBe(false);
  });

  it('cada tipo tem nome e dica', () => {
    expect(new Set(OSINT_KINDS.map((kind) => kind.id)).size).toBe(OSINT_KINDS.length);
    expect(kindLabel('domain')).toBe('Domínio');
    expect(kindLabel('network')).toBe('Minha rede');
  });
});

describe('senha em vazamentos', () => {
  it('calcula o SHA-1 conhecido de "password"', async () => {
    expect(await sha1Hex('password')).toBe('5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8');
  });

  it('compara só o sufixo e ignora maiúsculas', () => {
    const hash = '5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8';
    expect(pwnedCount(hash, [['1E4C9B93F3F0682250B6CF8331B7EE68FD8', 9_545_824]])).toBe(9_545_824);
    expect(pwnedCount(hash, [['1e4c9b93f3f0682250b6cf8331b7ee68fd8', 3]])).toBe(3);
    expect(pwnedCount(hash, [['0000000000000000000000000000000000A', 7]])).toBe(0);
    expect(pwnedCount(hash, [])).toBe(0);
  });

  it('manda ao servidor só os 5 primeiros caracteres do hash', async () => {
    const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify({ suffixes: [['1E4C9B93F3F0682250B6CF8331B7EE68FD8', 42]] })));
    expect(await checkPassword('password', fetcher as unknown as typeof fetch)).toBe(42);
    const url = String(fetcher.mock.calls[0][0]);
    expect(url).toBe('/api/osint/pwned/5BAA6');
    expect(url).not.toContain('password');
    expect(JSON.stringify(fetcher.mock.calls)).not.toContain('1E4C9B93');
  });

  it('repassa o motivo quando o servidor recusa', async () => {
    const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify({ detail: 'O Olho de Deus está desligado.' }), { status: 403 }));
    await expect(checkPassword('x', fetcher as unknown as typeof fetch)).rejects.toThrow('O Olho de Deus está desligado.');
  });
});
