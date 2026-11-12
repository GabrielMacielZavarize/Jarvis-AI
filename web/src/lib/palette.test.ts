import { describe, expect, it, vi } from 'vitest';
import { buildCommands, examplePhrase, freeTextCommand, normalizeText, osintCommand, type PaletteContext, searchCommands } from './palette';
import { DEFAULT_PREFS } from './prefs';
import { VIEWS } from './views';

function context(over: Partial<PaletteContext> = {}): PaletteContext {
  return {
    view: 'home',
    connected: false,
    demo: false,
    canConnect: true,
    busy: false,
    micEnabled: true,
    cinema: false,
    prefs: DEFAULT_PREFS,
    enabledTools: null,
    hasCards: false,
    setView: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    toggleMic: vi.fn(),
    startDemo: vi.fn(),
    setCinema: vi.fn(),
    setPrefs: vi.fn(),
    resetLayout: vi.fn(),
    clearCards: vi.fn(),
    send: vi.fn(),
    ...over,
  };
}

const ids = (ctx: PaletteContext) => buildCommands(ctx).map((command) => command.id);

describe('comandos da paleta', () => {
  it('oferece cada área e marca a que já está aberta', () => {
    const commands = buildCommands(context({ view: 'system' }));
    for (const view of VIEWS) expect(commands.some((command) => command.id === `view:${view.id}`)).toBe(true);
    expect(commands.find((command) => command.id === 'view:system')?.disabled).toBeTruthy();
    expect(commands.find((command) => command.id === 'view:home')?.disabled).toBeUndefined();
  });

  it('troca iniciar por encerrar conforme o link', () => {
    expect(ids(context())).toContain('link:start');
    expect(ids(context())).toContain('link:demo');
    expect(ids(context())).not.toContain('link:mic');
    const live = ids(context({ connected: true }));
    expect(live).toContain('link:stop');
    expect(live).toContain('link:mic');
    expect(live).not.toContain('link:start');
    expect(buildCommands(context({ canConnect: false })).find((command) => command.id === 'link:start')?.disabled).toMatch(/\.env/);
  });

  it('manda o exemplo do protocolo só com o link aberto e a ferramenta ligada', () => {
    const offline = buildCommands(context()).find((command) => command.id === 'protocol:get_weather');
    expect(offline?.disabled).toBeTruthy();
    const ctx = context({ connected: true, enabledTools: ['get_weather'] });
    const commands = buildCommands(ctx);
    const weather = commands.find((command) => command.id === 'protocol:get_weather');
    expect(weather?.disabled).toBeUndefined();
    weather?.run();
    expect(ctx.send).toHaveBeenCalledWith('Como está o tempo em Lisboa?');
    expect(commands.find((command) => command.id === 'protocol:open_app')?.disabled).toBe('Desativado no .env');
    // Na simulação não há agente para receber o texto.
    expect(buildCommands(context({ connected: true, demo: true })).find((c) => c.id === 'protocol:get_weather')?.disabled).toBeTruthy();
  });

  it('o modo cinema volta ao Painel antes de ligar', () => {
    const ctx = context({ view: 'settings' });
    buildCommands(ctx)
      .find((command) => command.id === 'look:cinema')
      ?.run();
    expect(ctx.setView).toHaveBeenCalledWith('home');
    expect(ctx.setCinema).toHaveBeenCalledWith(true);
  });

  it('só oferece limpar as projeções quando há alguma', () => {
    expect(ids(context())).not.toContain('look:clear');
    expect(ids(context({ hasCards: true }))).toContain('look:clear');
  });
});

describe('busca da paleta', () => {
  const commands = buildCommands(context({ connected: true }));

  it('sem texto devolve tudo na ordem', () => {
    expect(searchCommands(commands, '   ')).toEqual(commands);
  });

  it('ignora acentos e maiúsculas e exige todas as palavras', () => {
    expect(searchCommands(commands, 'AJUSTES')[0].id).toBe('view:settings');
    expect(searchCommands(commands, 'diagnostico')[0].id).toBe('protocol:run_diagnostics');
    expect(searchCommands(commands, 'qualidade economia').map((command) => command.id)).toEqual(['quality:low']);
    expect(searchCommands(commands, 'xyzzy')).toEqual([]);
  });

  it('acha pela palavra-chave e pelo exemplo, com o nome valendo mais', () => {
    expect(searchCommands(commands, 'tema').some((command) => command.id.startsWith('theme:'))).toBe(true);
    expect(searchCommands(commands, 'spotify').map((command) => command.id)).toContain('protocol:open_app');
    // O nome do comando vale mais que o exemplo: os dois "microfone" vêm antes de quem só o cita.
    const mic = searchCommands(commands, 'microfone').map((command) => command.id);
    expect(mic.slice(0, 2).sort()).toEqual(['link:mic', 'protocol:check_microphone']);
  });

  it('deixa por último o que não dá para rodar agora', () => {
    const offline = buildCommands(context({ view: 'home' }));
    const found = searchCommands(offline, 'painel');
    expect(found[found.length - 1].disabled).toBeTruthy();
    expect(found[0].disabled).toBeUndefined();
  });
});

describe('texto livre', () => {
  it('vira um comando de enviar ao Jarvis', () => {
    const ctx = context({ connected: true });
    const command = freeTextCommand(ctx, '  que horas são em Tóquio?  ');
    expect(command?.label).toContain('que horas são em Tóquio?');
    command?.run();
    expect(ctx.send).toHaveBeenCalledWith('que horas são em Tóquio?');
  });

  it('fica apagado sem link e some com texto curto demais', () => {
    expect(freeTextCommand(context(), 'oi jarvis')?.disabled).toBeTruthy();
    expect(freeTextCommand(context({ connected: true }), 'a')).toBeNull();
  });
});

describe('consulta pelo Olho de Deus', () => {
  it('oferece consultar o que tem formato de IP, domínio, link, CNPJ, CEP ou email', () => {
    const consult = vi.fn();
    const command = osintCommand(' 8.8.8.8 ', true, consult);
    expect(command?.label).toBe('Consultar IP: 8.8.8.8');
    command?.run();
    expect(consult).toHaveBeenCalledWith('8.8.8.8');
    expect(osintCommand('github.com', true, consult)?.label).toContain('Domínio');
    expect(osintCommand('https://bit.ly/x', true, consult)?.label).toContain('Link');
    expect(osintCommand('00.000.000/0001-91', true, consult)?.label).toContain('CNPJ');
  });

  it('não atrapalha a busca de comandos nem aparece com o protocolo desligado', () => {
    const consult = vi.fn();
    // Uma palavra solta seria "usuário" e dois dígitos, "DDD": comuns demais na paleta.
    expect(osintCommand('ajustes', true, consult)).toBeNull();
    expect(osintCommand('48', true, consult)).toBeNull();
    expect(osintCommand('123.456.789-09', true, consult)).toBeNull();
    expect(osintCommand('8.8.8.8', false, consult)).toBeNull();
  });
});

describe('utilitários', () => {
  it('normaliza e tira a primeira frase de exemplo', () => {
    expect(normalizeText('  Olá, Módulo-7! ')).toBe('ola modulo 7');
    expect(examplePhrase('“Abra o Spotify.” · “Feche o Discord.”')).toBe('Abra o Spotify.');
    expect(examplePhrase('')).toBe('');
  });
});
