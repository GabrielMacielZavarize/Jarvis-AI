import { beforeEach, describe, expect, it } from 'vitest';
import { useHud } from './hudStore';

const weather = {
  location: 'Criciúma',
  latitude: -28.68,
  longitude: -49.37,
  current: { temperature: 24, humidity: 60, wind: 10, code: 0, label: 'Céu limpo' },
  daily: [],
};

describe('runPanelCommand', () => {
  beforeEach(() => {
    useHud.setState({ cards: [], expandedId: null });
    useHud.getState().pushCard('weather', weather);
    useHud.getState().pushCard('search', { query: 'estrogonofe', results: [] });
    useHud.getState().pushCard('note', { title: 'Receita', content: 'passo 1' });
  });

  it('closes only the requested panels and reports what is left', () => {
    const result = useHud.getState().runPanelCommand('close', ['weather', 'search', 'timer']);

    expect(result.changed.sort()).toEqual(['search', 'weather']);
    expect(result.open).toEqual(['note']);
    expect(useHud.getState().cards.map((card) => card.kind)).toEqual(['note']);
  });

  it('reports nothing changed when the panel is not open', () => {
    const result = useHud.getState().runPanelCommand('close', ['timer']);
    expect(result.changed).toEqual([]);
    expect(result.open).toHaveLength(3);
  });

  it('expands and collapses a panel', () => {
    const expanded = useHud.getState().runPanelCommand('expand', ['weather']);
    const weatherCard = useHud.getState().cards.find((card) => card.kind === 'weather');

    expect(expanded.changed).toEqual(['weather']);
    expect(useHud.getState().expandedId).toBe(weatherCard?.id);

    useHud.getState().runPanelCommand('collapse', []);
    expect(useHud.getState().expandedId).toBeNull();
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
    expect(result.changed).toEqual(['install']);
    expect(useHud.getState().cards).toEqual([]);
  });
});
