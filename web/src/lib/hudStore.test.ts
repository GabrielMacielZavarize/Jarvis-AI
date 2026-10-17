import { beforeEach, describe, expect, it } from 'vitest';
import { trimCards, useHud } from './hudStore';
import { describeMicrophone } from './microphone';
import { parseHudRequest } from './panels';
import type { HudCard } from './types';

const weather = {
  location: 'Criciúma',
  latitude: -28.68,
  longitude: -49.37,
  current: { temperature: 24, humidity: 60, wind: 10, code: 0, label: 'Céu limpo' },
  daily: [],
};

const kinds = () => useHud.getState().cards.map((card) => card.kind);

describe('runPanelCommand', () => {
  beforeEach(() => {
    useHud.setState({ cards: [], expandedId: null });
    useHud.getState().pushCard('weather', weather);
    useHud.getState().pushCard('search', { query: 'estrogonofe', results: [] });
    useHud.getState().pushCard('note', { title: 'Receita', content: 'passo 1' });
  });

  it('closes only the requested panels and reports what is left', () => {
    const result = useHud.getState().runPanelCommand('close', ['weather', 'search', 'timer']);

    expect(result.changed.map((panel) => panel.kind).sort()).toEqual(['search', 'weather']);
    expect(result.open.map((panel) => panel.kind)).toEqual(['note']);
    expect(result.unmatched).toEqual(['timer']);
    expect(kinds()).toEqual(['note']);
  });

  it('reports nothing changed when the panel is not open', () => {
    const result = useHud.getState().runPanelCommand('close', ['timer']);
    expect(result.changed).toEqual([]);
    expect(result.open).toHaveLength(3);
  });

  it('lists every panel with its kind and the title shown on screen, newest first', () => {
    useHud.getState().pushCard('screen', { url: 'blob:print', label: 'tela 2', takenAt: 1 });
    useHud.getState().pushCard('media', { service: 'YouTube', title: 'lo-fi', url: 'https://youtu.be/x' });

    const { open } = useHud.getState().runPanelCommand('list', []);

    expect(open.map(({ kind, title, detail }) => ({ kind, title, detail }))).toEqual([
      { kind: 'media', title: 'Reprodução', detail: 'YouTube · lo-fi' },
      { kind: 'screen', title: 'Leitura de tela', detail: 'tela 2' },
      { kind: 'note', title: 'Receita', detail: '' },
      { kind: 'search', title: 'Pesquisa', detail: '"estrogonofe"' },
    ]);
  });

  it('closes the screen reading panel by kind or by its title', () => {
    useHud.getState().pushCard('screen', { url: 'blob:print', label: 'tela 2', takenAt: 1 });
    expect(useHud.getState().runPanelCommand('close', ['screen']).changed.map((p) => p.title)).toEqual(['Leitura de tela']);

    useHud.getState().pushCard('screen', { url: 'blob:print', label: 'tela 2', takenAt: 2 });
    const byTitle = useHud.getState().runPanelCommand('close', ['a aba de leitura de tela']);
    expect(byTitle.changed.map((p) => p.kind)).toEqual(['screen']);
    expect(kinds()).not.toContain('screen');
  });

  it('closes the "Reprodução" panel instead of anything else', () => {
    useHud.getState().pushCard('media', { service: 'YouTube', title: 'lo-fi', url: 'https://youtu.be/x' });
    const result = useHud.getState().runPanelCommand('close', ['aba de reprodução']);
    expect(result.changed.map((p) => p.kind)).toEqual(['media']);
    expect(kinds()).toEqual(['note', 'search', 'weather']);
  });

  it('"last" closes the most recent panel, e.g. a timer that just finished', () => {
    useHud.getState().pushCard('timer', { id: 't1', label: 'macarrão', duration_s: 60, ends_at: Date.now() + 60_000, status: 'running' });
    useHud.getState().pushCard('weather', { ...weather, location: 'Lisboa' });
    // The "done" event re-pushes the timer, which makes it the newest panel again.
    useHud.getState().pushCard('timer', { id: 't1', label: 'macarrão', status: 'done' });

    const result = useHud.getState().runPanelCommand('close', ['last']);
    expect(result.changed.map((p) => p.detail)).toEqual(['macarrão · concluído']);
    expect(kinds()).toEqual(['weather', 'note', 'search']);
  });

  it('expands a panel by the words of its title or subject', () => {
    useHud.getState().pushCard('note', { title: 'Lista de compras: estrogonofe de frango', content: '- frango' });
    useHud.getState().pushCard('email', { status: 'draft', to: 'gabriel@example.com', subject: 'Reunião de sexta', code: '123456' });

    const note = useHud.getState().runPanelCommand('expand', ['rascunho lista de compras estrogonofe de frango']);
    expect(note.changed.map((p) => p.title)).toEqual(['Lista de compras: estrogonofe de frango']);
    expect(note.changed[0].expanded).toBe(true);

    const email = useHud.getState().runPanelCommand('expand', ['rascunho reunião de sexta']);
    expect(email.changed.map((p) => p.kind)).toEqual(['email']);
    expect(useHud.getState().expandedId).toBe(email.changed[0].id);
  });

  it('does not guess when the words match no panel', () => {
    const result = useHud.getState().runPanelCommand('expand', ['planilha de gastos']);
    expect(result.changed).toEqual([]);
    expect(result.unmatched).toEqual(['planilha de gastos']);
    expect(useHud.getState().expandedId).toBeNull();
  });

  it('expands and collapses a panel', () => {
    const expanded = useHud.getState().runPanelCommand('expand', ['weather']);
    const weatherCard = useHud.getState().cards.find((card) => card.kind === 'weather');

    expect(expanded.changed.map((p) => p.kind)).toEqual(['weather']);
    expect(useHud.getState().expandedId).toBe(weatherCard?.id);

    const collapsed = useHud.getState().runPanelCommand('collapse', []);
    expect(collapsed.changed.map((p) => p.kind)).toEqual(['weather']);
    expect(useHud.getState().expandedId).toBeNull();
    expect(useHud.getState().runPanelCommand('collapse', []).changed).toEqual([]);
  });

  it('closing the expanded panel also leaves expanded mode', () => {
    useHud.getState().runPanelCommand('expand', ['weather']);
    useHud.getState().runPanelCommand('close', ['weather']);
    expect(useHud.getState().expandedId).toBeNull();
  });

  it('close_all clears everything', () => {
    const result = useHud.getState().runPanelCommand('close_all', []);
    expect(result.changed).toHaveLength(3);
    expect(useHud.getState().cards).toEqual([]);
  });
});

describe('install panel', () => {
  beforeEach(() => {
    useHud.setState({ cards: [], expandedId: null });
  });

  it('keeps a single install panel that follows search → confirmation → result', () => {
    const vlc = { name: 'VLC media player', id: 'VideoLAN.VLC', version: '3.0.24', source: 'winget' as const };
    useHud.getState().pushCard('install', { status: 'results', query: 'vlc', candidates: [vlc] });
    useHud.getState().pushCard('install', { status: 'pending', package: vlc, code: '482913' });
    useHud.getState().pushCard('install', { status: 'installed', package: vlc, message: 'instalado com sucesso' });

    const cards = useHud.getState().cards;
    expect(cards).toHaveLength(1);
    expect(cards[0].kind).toBe('install');
    expect(cards[0].data).toMatchObject({ status: 'installed' });
  });

  it('can be closed by voice like the other panels', () => {
    useHud.getState().pushCard('install', { status: 'cancelled' });
    const result = useHud.getState().runPanelCommand('close', ['install']);
    expect(result.changed.map((panel) => panel.kind)).toEqual(['install']);
    expect(useHud.getState().cards).toEqual([]);
  });
});

describe('card limit', () => {
  beforeEach(() => useHud.setState({ cards: [], expandedId: null }));

  it('keeps an email draft waiting for confirmation and running timers when panels pile up', () => {
    const hud = useHud.getState();
    hud.pushCard('email', { status: 'draft', to: 'gabriel@example.com', subject: 'Lista de compras', code: '654321' });
    hud.pushCard('timer', { id: 't1', label: 'forno', duration_s: 600, ends_at: Date.now() + 600_000, status: 'running' });
    hud.pushCard('weather', weather);
    hud.pushCard('search', { query: 'frango', results: [] });
    hud.pushCard('news', { topic: 'tecnologia', items: [] });
    hud.pushCard('time', { location: 'Horário local', timezone: 'local', iso: '2026-10-17T12:00:00', utc_offset: 'UTC-03:00' });

    expect(kinds()).toEqual(['time', 'news', 'timer', 'email']);
  });

  it('still caps the column when everything is pinned', () => {
    const now = Date.now();
    const timers = Array.from({ length: 6 }, (_, index) => ({
      id: `card-${index}`,
      kind: 'timer',
      createdAt: now - index,
      data: { id: `t${index}`, label: `t${index}`, ends_at: now + 60_000, status: 'running' },
    })) as HudCard[];
    expect(trimCards(timers, now).map((card) => card.id)).toEqual(['card-0', 'card-1', 'card-2', 'card-3']);
  });
});

describe('parseHudRequest', () => {
  it('reads panel targets, legacy kinds and the other actions', () => {
    expect(parseHudRequest('{"action":"close","targets":["Leitura de tela"]}')).toEqual({ action: 'close', targets: ['Leitura de tela'] });
    expect(parseHudRequest('{"action":"close","kinds":["screen"]}')).toEqual({ action: 'close', targets: ['screen'] });
    expect(parseHudRequest('{"action":"mic"}')).toEqual({ action: 'mic' });
    expect(parseHudRequest('{"action":"end_session"}')).toEqual({ action: 'end_session' });
    expect(parseHudRequest('not json')).toEqual({ action: 'list', targets: [] });
    expect(parseHudRequest('{"action":"rm -rf","targets":[1,"x"]}')).toEqual({ action: 'list', targets: ['x'] });
  });
});

describe('describeMicrophone', () => {
  const devices = [
    { deviceId: 'default', label: 'Padrão - Microfone (Realtek)' },
    { deviceId: 'communications', label: 'Comunicações - Microfone (Realtek)' },
    { deviceId: 'hyperx', label: 'Headset (HyperX Cloud)' },
    { deviceId: 'realtek', label: 'Microfone (Realtek)' },
  ];

  it('names the device being captured and how recently it had sound', () => {
    const report = describeMicrophone({
      trackLabel: 'Headset (HyperX Cloud)',
      deviceId: 'hyperx',
      devices,
      enabled: true,
      signalAt: 7_000,
      heardAt: null,
      now: 10_000,
    });
    expect(report).toEqual({
      label: 'Headset (HyperX Cloud)',
      device_id: 'hyperx',
      is_default: false,
      enabled: true,
      signal_s: 3,
      heard_s: null,
      available: ['Headset (HyperX Cloud)', 'Microfone (Realtek)'],
    });
  });

  it('falls back to the chosen device label before the track exists', () => {
    const report = describeMicrophone({ deviceId: 'default', devices, enabled: false, signalAt: null, heardAt: 9_000, now: 10_000 });
    expect(report.label).toBe('Padrão - Microfone (Realtek)');
    expect(report.is_default).toBe(true);
    expect(report.heard_s).toBe(1);
  });
});
