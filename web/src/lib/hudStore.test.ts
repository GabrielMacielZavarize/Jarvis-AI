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
