import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, type Page, test } from '@playwright/test';
import { THEMES } from '../src/lib/themes';

// O servidor grava a persona escolhida no persona.json da raiz; o do dono volta no fim.
const PERSONA_FILE = resolve(import.meta.dirname, '..', '..', 'persona.json');
let savedPersona: string | null = null;

test.beforeAll(() => {
  savedPersona = existsSync(PERSONA_FILE) ? readFileSync(PERSONA_FILE, 'utf-8') : null;
});

test.afterAll(() => {
  if (savedPersona === null) rmSync(PERSONA_FILE, { force: true });
  else writeFileSync(PERSONA_FILE, savedPersona, 'utf-8');
});

/** Abre o HUD com a persona do servidor, pula o boot e devolve os erros do console. */
async function openHud(page: Page, persona: string): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  const response = await page.request.post('/api/persona', { data: { persona } });
  expect(response.ok()).toBeTruthy();
  await page.goto('/');
  await page.locator('.boot').click();
  await expect(page.locator('.hud.hud--online')).toBeVisible();
  return errors;
}

for (const theme of THEMES) {
  test(`a persona ${theme.label} carrega com o núcleo e os painéis`, async ({ page }) => {
    const errors = await openHud(page, theme.id);

    await expect(page.locator('html')).toHaveAttribute('data-theme', theme.id);
    await expect(page.locator('.brand__name')).toHaveText(theme.brand);
    await expect(page.locator('main.app canvas')).toBeVisible();
    for (const panel of ['Briefing', 'Projeções', 'Transcrição', 'Registro']) {
      await expect(page.getByRole('region', { name: panel })).toBeVisible();
    }
    expect(errors).toEqual([]);
  });
}

test('a simulação passa pelos estados sem piscar e projeta os painéis', async ({ page }) => {
  test.setTimeout(90_000);
  const errors = await openHud(page, 'jarvis');

  // Cada troca do data-mode com o horário, desde antes do clique.
  await page.evaluate(() => {
    const app = document.querySelector('main.app')!;
    const log: { mode: string; at: number }[] = [{ mode: app.getAttribute('data-mode') ?? '', at: performance.now() }];
    (window as unknown as { modeLog: typeof log }).modeLog = log;
    new MutationObserver(() => {
      const mode = app.getAttribute('data-mode') ?? '';
      if (mode !== log[log.length - 1].mode) log.push({ mode, at: performance.now() });
    }).observe(app, { attributes: true, attributeFilter: ['data-mode'] });
  });

  await page.getByRole('button', { name: 'Simulação' }).click();
  await expect(page.locator('.chip--demo')).toBeVisible();

  // Clima, diagnóstico e timer: as três primeiras projeções do roteiro.
  const cards = page.locator('.stage .panel.card');
  await expect(cards).toHaveCount(3, { timeout: 45_000 });
  await expect(page.getByRole('region', { name: 'Transcrição' })).toContainText('São Paulo');
  await expect(page.getByRole('region', { name: 'Registro' })).toContainText('Modo simulação ativado');

  const log = await page.evaluate(() => (window as unknown as { modeLog: { mode: string; at: number }[] }).modeLog);
  const seen = new Set(log.map((entry) => entry.mode));
  for (const mode of ['connecting', 'speaking', 'listening', 'thinking']) expect(seen).toContain(mode);

  // Fora do link, nenhum estado aparece por menos de 300 ms (o último ainda está na tela) nem some
  // voltando ao anterior: o respiro entre as frases do clima não pode virar "falando, ouvindo, falando".
  // Os timers esticam no Chromium sem GPU, por isso a volta ao estado anterior também conta. Um travamento
  // da thread principal pode soltar os dois timers juntos e trocar o estado por menos de um quadro: isso
  // não chega à tela e sai do registro antes da conta.
  const painted = log
    .filter((entry, index) => index === log.length - 1 || log[index + 1].at - entry.at >= 17)
    .filter((entry, index, kept) => index === 0 || entry.mode !== kept[index - 1].mode);
  const link = ['offline', 'standby', 'connecting'];
  const flickers = painted
    .slice(1, -1)
    .map((entry, index) => ({
      ...entry,
      held: painted[index + 2].at - entry.at,
      around: [painted[index].mode, painted[index + 2].mode],
    }))
    .filter((entry) => !link.includes(entry.mode) && (entry.held < 300 || entry.around[0] === entry.around[1]));
  expect(flickers).toEqual([]);

  await page.getByRole('button', { name: 'Sair da simulação' }).click();
  await expect(page.locator('.chip--demo')).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Projeções' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('as abas trocam de área e o Painel volta com Esc', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const app = page.locator('main.app');
  const tabs = page.getByRole('navigation', { name: 'Áreas do HUD' });

  await expect(app).toHaveAttribute('data-view', 'home');
  await tabs.getByRole('button', { name: 'Sistema' }).click();
  await expect(app).toHaveAttribute('data-view', 'system');
  for (const panel of ['Sistema', 'Protocolos']) await expect(page.getByRole('region', { name: panel }).first()).toBeVisible();
  await expect(page.getByRole('region', { name: 'Transcrição' })).toHaveCount(0);
  // O dock continua à mão em qualquer área.
  await expect(page.getByRole('button', { name: 'Simulação' })).toBeVisible();

  await page.keyboard.press('5');
  await expect(app).toHaveAttribute('data-view', 'settings');
  for (const panel of ['Aparência', 'Áudio', 'Atalhos']) await expect(page.getByRole('region', { name: panel })).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(app).toHaveAttribute('data-view', 'home');
  await expect(page.getByRole('region', { name: 'Briefing' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('a paleta de comandos abre com Ctrl+K, busca e executa', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const palette = page.getByRole('dialog', { name: 'Paleta de comandos' });

  await page.keyboard.press('Control+k');
  await expect(palette).toBeVisible();
  await page.keyboard.type('ajustes');
  await expect(palette.getByRole('option').first()).toContainText('Ajustes');
  await page.keyboard.press('Enter');
  await expect(palette).toHaveCount(0);
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'settings');

  // A persona troca pela paleta e o Esc fecha sem mexer na área aberta.
  await page.keyboard.press('Control+k');
  await page.keyboard.type('mark');
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'mark3');
  await page.keyboard.press('Control+k');
  await expect(palette).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(palette).toHaveCount(0);
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'settings');
  expect(errors).toEqual([]);
});

test('as colunas do Painel rolam em vez de cortar os painéis', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 620 });
  await openHud(page, 'jarvis');
  for (const side of ['left', 'right']) {
    const column = page.locator(`.hud__${side}`);
    await expect(column).toHaveCSS('overflow-y', 'auto');
    // Nenhum painel é espremido: a coluna toda cabe na própria rolagem.
    const fits = await column.evaluate((element) =>
      [...element.querySelectorAll(':scope > .slot > *')].every((panel) => panel.scrollHeight <= panel.clientHeight + 1),
    );
    expect(fits, `coluna ${side}`).toBe(true);
  }
});

test('no celular o botão principal aparece inteiro e as áreas ficam na barra de baixo', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  const errors = await openHud(page, 'jarvis');

  const primary = page.locator('.dock .btn--primary');
  await expect(primary).toBeVisible();
  expect(await primary.evaluate((button) => button.scrollWidth <= button.clientWidth)).toBe(true);
  const box = await primary.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);

  const bar = page.locator('.nav--bar');
  await expect(bar).toBeVisible();
  await expect(page.locator('.nav--top')).toBeHidden();
  await bar.getByRole('button', { name: 'Sistema' }).tap();
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'system');
  await expect(page.getByRole('region', { name: 'Sistema' }).first()).toBeVisible();
  // A página não rola de lado.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await context.close();
});


const IP_RESULT = {
  kind: 'ip',
  label: 'IP',
  target: '8.8.8.8',
  title: '8.8.8.8',
  summary: 'Mountain View, Califórnia, Estados Unidos · Google LLC',
  verdict: null,
  sections: [{ title: 'Rede', rows: [['Provedor', 'Google LLC'], ['ASN', 'AS15169']] }],
  lists: [],
  point: { name: 'Mountain View', lat: 37.386, lon: -122.0838 },
  notes: ['A localização de um IP é a do provedor, não a de uma pessoa.'],
  sources: ['ipwho.is'],
  ts: 1_800_000_000,
};

test('o Olho de Deus reconhece o que foi digitado, consulta e recusa dados pessoais', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const asked: unknown[] = [];
  await page.route('**/api/osint', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    asked.push(route.request().postDataJSON());
    await route.fulfill({ json: IP_RESULT });
  });

  await page.keyboard.press('3');
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'eye');
  const field = page.getByRole('textbox', { name: 'O que consultar' });
  await expect(field).toBeFocused();
  const go = page.getByRole('button', { name: 'Consultar' });

  // CPF: o botão nem liga e o aviso explica por quê.
  await field.fill('123.456.789-09');
  await expect(page.locator('.eye__hint')).toContainText('não consulta dados pessoais');
  await expect(go).toBeDisabled();

  await field.fill('8.8.8.8');
  await expect(page.locator('.eye__hint')).toContainText('Reconhecido como IP');
  await go.click();
  const result = page.getByRole('region', { name: 'IP', exact: true });
  await expect(result).toContainText('Mountain View');
  await expect(result).toContainText('AS15169');
  await expect(result.locator('canvas')).toBeVisible();
  expect(asked).toEqual([{ kind: null, target: '8.8.8.8' }]);

  // A rede do PC vem desligada no .env de fábrica.
  await expect(page.getByRole('button', { name: 'Minha rede' })).toBeDisabled();
  expect(errors).toEqual([]);
});

test('a senha é conferida sem sair do navegador', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const requested: string[] = [];
  await page.route('**/api/osint/pwned/*', async (route) => {
    requested.push(new URL(route.request().url()).pathname);
    await route.fulfill({ json: { prefix: '5BAA6', suffixes: [['1E4C9B93F3F0682250B6CF8331B7EE68FD8', 9545824]] } });
  });

  await page.keyboard.press('3');
  const field = page.getByLabel('Senha para conferir em vazamentos');
  await field.fill('password');
  await page.getByRole('button', { name: 'Conferir' }).click();
  await expect(page.locator('.osint__verdict--danger')).toContainText('9.545.824');
  // Só os 5 primeiros caracteres do SHA-1 foram ao servidor, e o campo esvaziou.
  expect(requested).toEqual(['/api/osint/pwned/5BAA6']);
  await expect(field).toHaveValue('');

  await field.fill('uma senha que ninguém usou 8f3k!');
  await page.getByRole('button', { name: 'Conferir' }).click();
  await expect(page.locator('.osint__verdict--ok')).toBeVisible();
  expect(requested.every((path) => /^\/api\/osint\/pwned\/[0-9A-F]{5}$/.test(path))).toBe(true);
  expect(errors).toEqual([]);
});

test('a paleta consulta um domínio digitado', async ({ page }) => {
  await openHud(page, 'jarvis');
  await page.route('**/api/osint', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    await route.fulfill({ json: { ...IP_RESULT, kind: 'domain', label: 'Domínio', target: 'github.com', title: 'github.com', point: null } });
  });
  await page.keyboard.press('Control+k');
  await page.keyboard.type('github.com');
  await expect(page.getByRole('option').first()).toContainText('Consultar Domínio: github.com');
  await page.keyboard.press('Enter');
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'eye');
  await expect(page.getByRole('region', { name: 'Domínio', exact: true })).toContainText('github.com');
});


const TASKS = {
  enabled: true,
  tasks: [
    { id: 't1', text: 'Fechar o relatório', done: false, due: '2026-11-12', due_label: 'hoje', overdue: false },
    { id: 't2', text: 'Ligar pro contador', done: false, due: '2026-11-10', due_label: 'atrasada desde 10/11', overdue: true },
  ],
  notes: [{ id: 'n1', text: 'Ideia: painel de consumo', created_at: '2026-11-12T09:00:00-03:00' }],
  open: 2,
  overdue: 1,
  due_today: 1,
  done_today: 0,
};

test('o Dia a dia mostra tarefas, marca uma como feita e anota outra', async ({ page }) => {
  const calls: string[] = [];
  let state = TASKS;
  await page.route('**/api/tasks**', async (route) => {
    const request = route.request();
    calls.push(`${request.method()} ${new URL(request.url()).pathname}`);
    if (request.method() === 'PATCH') {
      state = { ...state, open: 1, due_today: 0, done_today: 1, tasks: state.tasks.map((task) => (task.id === 't1' ? { ...task, done: true } : task)) };
    }
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as { text: string };
      state = { ...state, open: state.open + 1, tasks: [...state.tasks, { id: 't3', text: body.text, done: false, due: null, due_label: '', overdue: false }] };
    }
    await route.fulfill({ json: state });
  });
  // As tarefas falsas entram antes de o HUD abrir: o Briefing do Painel já pede a lista ao carregar.
  const errors = await openHud(page, 'jarvis');

  await page.keyboard.press('2');
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'day');
  const panel = page.getByRole('region', { name: 'Tarefas' });
  await expect(panel).toContainText('2 abertas · 1 atrasada · 1 para hoje');
  await expect(panel.locator('.task--late')).toContainText('Ligar pro contador');

  await panel.getByRole('checkbox', { name: 'Fechar o relatório' }).check();
  await expect(panel.locator('.task--done')).toContainText('Fechar o relatório');
  await expect(panel).toContainText('1 aberta');

  await panel.getByRole('textbox', { name: 'Nova tarefa' }).fill('Comprar café');
  await panel.getByRole('textbox', { name: 'Nova tarefa' }).press('Enter');
  await expect(panel).toContainText('Comprar café');
  await expect(panel.getByRole('textbox', { name: 'Nova tarefa' })).toHaveValue('');
  expect(calls).toContain('PATCH /api/tasks/t1');
  expect(calls).toContain('POST /api/tasks');

  // De volta ao Painel, o Briefing mostra as mesmas tarefas (o foco está no campo, então vai pelo clique).
  await page.getByRole('navigation', { name: 'Áreas do HUD' }).getByRole('button', { name: 'Painel' }).click();
  await expect(page.getByRole('region', { name: 'Briefing' })).toContainText('Comprar café');
  expect(errors).toEqual([]);
});

test('a sessão de foco conta no painel, aparece no topo e sobrevive a recarregar', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  await page.keyboard.press('2');
  const panel = page.getByRole('region', { name: 'Foco' });
  await panel.getByRole('spinbutton', { name: 'Foco (min)' }).fill('10');
  await panel.getByRole('spinbutton', { name: 'Blocos' }).fill('2');
  await panel.getByRole('button', { name: 'Começar o foco' }).click();

  await expect(panel.getByRole('timer')).toContainText('Foco 1/2');
  await expect(panel.getByRole('timer')).toContainText(/^(10:00|09:5\d)/);
  const chip = page.locator('.chip--focus');
  await expect(chip).toContainText('Foco');

  // O bloco em andamento fica à vista em qualquer área e leva de volta ao Dia a dia.
  await page.keyboard.press('1');
  await expect(chip).toBeVisible();
  await page.reload();
  await page.locator('.boot').click();
  await expect(page.locator('.hud.hud--online')).toBeVisible();
  await expect(page.locator('.chip--focus')).toContainText('1/2');
  await page.locator('.chip--focus').click();
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'day');

  await page.getByRole('region', { name: 'Foco' }).getByRole('button', { name: 'Pular bloco' }).click();
  await expect(page.getByRole('region', { name: 'Foco' }).getByRole('timer')).toContainText('Pausa 1/2');
  await page.getByRole('region', { name: 'Foco' }).getByRole('button', { name: 'Encerrar' }).click();
  await expect(page.locator('.chip--focus')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('o foco mudado fora da aba (voz, bandeja) aparece no HUD sem recarregar', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  await expect(page.locator('.chip--focus')).toHaveCount(0);

  // O servidor é a fonte da verdade: o que a voz ou a bandeja fazem chega na aba em poucos segundos.
  const send = async (data: Record<string, unknown>) => {
    const response = await page.request.post('/api/focus', { data });
    expect(response.ok()).toBeTruthy();
    return response.json();
  };
  const started = await send({ command: 'start', work: 5, rest: 1, cycles: 2 });
  expect(started).toMatchObject({ running: true, phase: 'work', cycle: 1, cycles: 2, paused: false });
  await expect(page.locator('.chip--focus')).toContainText('1/2', { timeout: 10_000 });
  await expect(page.locator('.chip--focus')).toContainText('Foco');

  await page.keyboard.press('2');
  const timer = page.getByRole('region', { name: 'Foco' }).getByRole('timer');
  await expect(timer).toContainText('Foco 1/2');
  await expect(timer).toContainText(/^(05:00|04:5\d)/);

  const skipped = await send({ command: 'skip' });
  expect(skipped.last_event).toMatchObject({ kind: 'rest', title: 'Hora da pausa' });
  await expect(timer).toContainText('Pausa 1/2', { timeout: 10_000 });
  // A troca feita fora da aba também mostra a notificação do HUD.
  await expect(page.getByText('Hora da pausa').first()).toBeVisible({ timeout: 10_000 });

  await send({ command: 'stop' });
  await expect(page.locator('.chip--focus')).toHaveCount(0, { timeout: 10_000 });
  expect(errors).toEqual([]);
});
