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
    for (const panel of ['Sistema', 'Protocolos', 'Transcrição', 'Registro']) {
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
  await expect(page.getByRole('region', { name: 'Protocolos' })).toBeVisible();
  expect(errors).toEqual([]);
});
