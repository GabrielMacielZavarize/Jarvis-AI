import { beforeEach, describe, expect, it } from 'vitest';
import { useHud } from './hudStore';
import { matchPanels, panelDetail, panelTitle } from './panels';
import type { ExplainData, HudCard } from './types';

const base: ExplainData = {
  status: 'done',
  task: 'explain_error',
  task_label: 'Explicação do erro',
  source: "janela 'PhpStorm'",
  via: 'texto da janela',
  title: 'TypeError: Cannot read properties of undefined',
  explanation: 'O objeto ainda não existe.',
  cause: 'user é undefined',
  fix: 'Use optional chaining.',
  blocks: [{ language: 'js', code: 'user?.name', label: 'app.js' }],
  message: '',
};

describe('screen assistant panel (TEL-31)', () => {
  beforeEach(() => useHud.getState().clearCards());

  it('is called Assistente de tela, with the task and the error as detail', () => {
    const card: HudCard = { id: 'e1', kind: 'explain', data: base, createdAt: 1 };
    expect(panelTitle(card)).toBe('Assistente de tela');
    expect(panelDetail(card)).toBe('Explicação do erro · TypeError: Cannot read properties of undefined');
    expect(panelDetail({ ...card, data: { ...base, title: '' } })).toBe("Explicação do erro · janela 'PhpStorm'");
  });

  it('can be closed by voice by its name', () => {
    const card: HudCard = { id: 'e1', kind: 'explain', data: base, createdAt: 1 };
    expect(matchPanels([card], ['explicação do erro']).matched).toHaveLength(1);
    expect(matchPanels([card], ['explain']).matched).toHaveLength(1);
  });

  it('updates the same panel from "lendo" to the answer instead of stacking', () => {
    const hud = useHud.getState();
    hud.pushCard('explain', { ...base, status: 'reading', title: '', blocks: [] });
    hud.pushCard('explain', base);
    hud.pushCard('explain', { ...base, copied: 0 });
    const cards = useHud.getState().cards;
    expect(cards).toHaveLength(1);
    expect(cards[0].kind === 'explain' && cards[0].data.copied).toBe(0);
  });
});
