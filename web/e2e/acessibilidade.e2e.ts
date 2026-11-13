import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, type Page, test } from '@playwright/test';
import { THEMES } from '../src/lib/themes';

// Melhoria 10: tamanho do texto, alto contraste e a revisão de acessibilidade das áreas novas.
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

const PREFS_KEY = 'jarvis.hud.prefs';

/**
 * Abre o HUD na persona do servidor e pula o boot. Com `prefs`, o navegador já começa com elas salvas
 * (o script roda em toda carga, então um teste que recarrega a página não passa `prefs`).
 */
async function openHud(page: Page, persona: string, prefs?: Record<string, unknown>): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  const response = await page.request.post('/api/persona', { data: { persona } });
  expect(response.ok()).toBeTruthy();
  if (prefs) {
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, JSON.stringify(value)),
      [PREFS_KEY, { theme: persona, ...prefs }] as const,
    );
  }
  await page.goto('/');
  await page.locator('.boot').click();
  // No celular emulado, com o PC ocupado, a cena pode levar mais que os 5 s de costume para abrir.
  await expect(page.locator('.hud.hud--online')).toBeVisible({ timeout: 20_000 });
  return errors;
}

const VIEWS = [
  { key: '1', view: 'home' },
  { key: '2', view: 'day' },
  { key: '3', view: 'eye' },
  { key: '4', view: 'system' },
  { key: '5', view: 'settings' },
];

/** Troca de área pela tecla e espera a área (que vem sob demanda) aparecer. */
async function goTo(page: Page, key: string, view: string) {
  // O foco no campo de uma área (o Olho de Deus o pega ao abrir) engole a tecla: sai dele antes.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press(key);
  await expect(page.locator('main.app')).toHaveAttribute('data-view', view);
  await expect(page.locator('main.app')).not.toHaveAttribute('data-pending', 'true');
  // As entradas dos painéis (0,8 s) terminam antes de medir.
  await page.waitForTimeout(1100);
}

/**
 * O que está cortado ou sobreposto na tela: caixas com `overflow` escondido cujo conteúdo passa da
 * borda (menos as que cortam com reticências de propósito), a página rolando de lado e a marca do HUD
 * por cima das abas ou do relógio. Os rótulos 3D do globo ficam de fora: o canvas os corta de propósito.
 */
async function findCut(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const visible = (el: Element) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const label = (el: Element) => `${el.tagName.toLowerCase()}${typeof el.className === 'string' && el.className ? `.${el.className.trim().split(/\s+/).join('.')}` : ''}`;
    for (const el of document.querySelectorAll('main.app *')) {
      if (el instanceof SVGElement || el.closest('svg, .sr-only, .scene') || el.tagName === 'CANVAS' || !visible(el)) continue;
      const style = getComputedStyle(el);
      const hiddenX = ['hidden', 'clip'].includes(style.overflowX);
      const hiddenY = ['hidden', 'clip'].includes(style.overflowY);
      if (!hiddenX && !hiddenY) continue;
      const box = el.getBoundingClientRect();
      // Onde o conteúdo termina: os filhos e o texto solto (os pseudo-elementos decorativos não contam).
      const parts: DOMRect[] = [...el.children].filter(visible).map((child) => child.getBoundingClientRect());
      for (const node of el.childNodes) {
        if (node.nodeType !== Node.TEXT_NODE || !node.textContent?.trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        parts.push(...range.getClientRects());
      }
      const right = Math.max(-Infinity, ...parts.map((rect) => rect.right));
      const bottom = Math.max(-Infinity, ...parts.map((rect) => rect.bottom));
      const text = (el.textContent ?? '').trim().slice(0, 30);
      if (hiddenX && style.textOverflow !== 'ellipsis' && right > box.right + 1) out.push(`X ${label(el)} ${Math.round(right)}>${Math.round(box.right)} “${text}”`);
      const clamped = style.webkitLineClamp && style.webkitLineClamp !== 'none';
      if (hiddenY && !clamped && bottom > box.bottom + 1) out.push(`Y ${label(el)} ${Math.round(bottom)}>${Math.round(box.bottom)} “${text}”`);
    }
    if (document.documentElement.scrollWidth > window.innerWidth + 1) {
      out.push(`PÁGINA rola de lado: ${document.documentElement.scrollWidth} > ${window.innerWidth}`);
    }
    // Um rótulo de aba cortado com reticências também é texto perdido.
    for (const tab of document.querySelectorAll('.nav--bar .nav__tab span')) {
      if (visible(tab) && tab.scrollWidth > tab.clientWidth + 0.5) out.push(`Aba cortada: ${tab.textContent}`);
    }
    const brand = document.querySelector('.brand__name')?.getBoundingClientRect();
    const hit = (a?: DOMRect, b?: DOMRect) => !!a && !!b && a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
    for (const selector of ['.nav--top', '.clock__time']) {
      const other = document.querySelector(selector);
      if (other && visible(other) && hit(brand, other.getBoundingClientRect())) out.push(`A marca está por cima de ${selector}`);
    }
    return [...new Set(out)];
  });
}

const TASKS = {
  enabled: true,
  tasks: [
    { id: 't1', text: 'Fechar o relatório do trimestre e mandar para a diretoria antes do almoço', done: false, due: '2026-11-13', due_label: 'hoje', overdue: false },
    { id: 't2', text: 'Ligar pro contador', done: false, due: '2026-11-10', due_label: 'atrasada desde 10/11', overdue: true },
  ],
  notes: [{ id: 'n1', text: 'Ideia: painel de consumo de energia da casa, com o gráfico do mês', created_at: '2026-11-12T09:00:00-03:00' }],
  open: 2,
  overdue: 1,
  due_today: 1,
  done_today: 0,
};

const DEVICES = {
  watching: true,
  learning: false,
  learning_until: null,
  unreviewed: 1,
  devices: [
    { mac: '00:1a:2b:3c:4d:5e', ip: '192.168.0.50', name: '', known: false, private: false, origin: 'novo', first_seen: '2026-11-13T11:00:00-03:00', last_seen: '2026-11-13T11:05:00-03:00' },
    { mac: 'da:a1:19:12:34:56', ip: '192.168.0.77', name: 'Celular da Ana', known: true, private: true, origin: 'aprendido', first_seen: '2026-11-13T10:00:00-03:00', last_seen: '2026-11-13T11:00:00-03:00' },
  ],
};

/** Respostas falsas para as áreas Dia a dia e Olho de Deus mostrarem conteúdo de verdade. */
async function mockAreas(page: Page) {
  await page.route('**/api/status', async (route) => {
    // Se a página já mudou quando a resposta chega (recarga, fim do teste), o navegador descarta a resposta: deixa passar.
    try {
      const response = await route.fetch();
      const body = await response.json();
      await route.fulfill({ response, json: { ...body, day: true, osint: { enabled: true, network: true, network_watch: true } } });
    } catch {
      await route.fallback().catch(() => undefined);
    }
  });
  await page.route('**/api/tasks**', (route) => route.fulfill({ json: TASKS }));
  await page.route('**/api/osint/network/devices**', (route) => route.fulfill({ json: DEVICES }));
}

// ───────────────────────── Tamanho do texto ─────────────────────────

test('o tamanho do texto muda em Ajustes, vale em todo o HUD e sobrevive a recarregar', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const size = (selector: string) => page.locator(selector).first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));

  await page.keyboard.press('5');
  await expect(page.locator('main.app')).toHaveAttribute('data-view', 'settings');
  const look = page.getByRole('region', { name: 'Aparência' });
  const group = look.getByRole('radiogroup', { name: 'Tamanho do texto' });
  await expect(group.getByRole('radio', { name: '100%' })).toHaveAttribute('aria-checked', 'true');
  await expect(group.getByRole('radio')).toHaveText(['90%', '100%', '110%', '120%', '130%', '140%']);
  const title = await size('.panel__title');
  const body = await size('.shortcuts li');

  await group.getByRole('radio', { name: '140%' }).click();
  await expect(group.getByRole('radio', { name: '140%' })).toHaveAttribute('aria-checked', 'true');
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue('--ts'))).toBe('1.4');
  expect(await size('.panel__title')).toBeCloseTo(title * 1.4, 0);
  expect(await size('.shortcuts li')).toBeCloseTo(body * 1.4, 0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('jarvis.hud.prefs') ?? '{}').textSize)).toBe(140);

  // O resto do HUD acompanha: os chips do topo, o Briefing e o dock também crescem.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('region', { name: 'Briefing' })).toBeVisible();
  expect(await size('.chip')).toBeCloseTo(12.5 * 1.4, 0);
  expect(await size('.dock__state')).toBeGreaterThan(13);

  // Recarregar guarda a escolha.
  await page.reload();
  await page.locator('.boot').click();
  await expect(page.locator('.hud.hud--online')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue('--ts'))).toBe('1.4');
  await page.keyboard.press('5');
  await expect(page.getByRole('radiogroup', { name: 'Tamanho do texto' }).getByRole('radio', { name: '140%' })).toHaveAttribute('aria-checked', 'true');
  expect(errors).toEqual([]);
});

test('a paleta de comandos aumenta, diminui e restaura o texto', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const palette = page.getByRole('dialog', { name: 'Paleta de comandos' });
  const scale = () => page.evaluate(() => document.documentElement.style.getPropertyValue('--ts'));

  await page.keyboard.press('Control+k');
  await page.keyboard.type('texto maior');
  await expect(palette.getByRole('option').first()).toContainText('Texto maior');
  await page.keyboard.press('Enter');
  await expect(palette).toHaveCount(0);
  expect(await scale()).toBe('1.1');

  await page.keyboard.press('Control+k');
  await page.keyboard.type('texto maior');
  await page.keyboard.press('Enter');
  expect(await scale()).toBe('1.2');

  await page.keyboard.press('Control+k');
  await page.keyboard.type('texto menor');
  await page.keyboard.press('Enter');
  expect(await scale()).toBe('1.1');

  await page.keyboard.press('Control+k');
  await page.keyboard.type('tamanho do texto 100');
  await expect(palette.getByRole('option').first()).toContainText('Tamanho do texto: 100%');
  await page.keyboard.press('Enter');
  expect(await scale()).toBe('1');
  expect(errors).toEqual([]);
});

for (const theme of THEMES) {
  test(`com o texto a 140% nada fica cortado no computador e no celular (${theme.label})`, async ({ page, browser }) => {
    test.setTimeout(120_000);
    // 1280×720 é o notebook comum: o pior caso de largura do computador.
    await page.setViewportSize({ width: 1280, height: 720 });
    await mockAreas(page);
    const errors = await openHud(page, theme.id, { textSize: 140 });
    expect(await page.evaluate(() => document.documentElement.style.getPropertyValue('--ts'))).toBe('1.4');
    for (const { key, view } of VIEWS) {
      await goTo(page, key, view);
      expect(await findCut(page), `${theme.label} no computador, área ${view}`).toEqual([]);
    }
    expect(errors).toEqual([]);

    const context = await browser.newContext({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true });
    const phone = await context.newPage();
    await mockAreas(phone);
    const phoneErrors = await openHud(phone, theme.id, { textSize: 140 });
    for (const { key, view } of VIEWS) {
      await goTo(phone, key, view);
      expect(await findCut(phone), `${theme.label} no celular, área ${view}`).toEqual([]);
    }
    expect(phoneErrors).toEqual([]);
    await context.close();
  });
}

for (const device of [
  { name: 'no computador', viewport: { width: 1280, height: 720 }, phone: false },
  { name: 'no celular', viewport: { width: 390, height: 844 }, phone: true },
]) {
  test(`os painéis projetados cabem com o texto a 140% ${device.name}`, async ({ browser }) => {
    test.setTimeout(90_000);
    const context = await browser.newContext({ viewport: device.viewport, isMobile: device.phone, hasTouch: device.phone });
    const page = await context.newPage();
    const errors = await openHud(page, 'jarvis', { textSize: 140 });
    await page.getByRole('button', { name: 'Simulação' }).click();
    // Clima, diagnóstico e timer: os três painéis do roteiro.
    await expect(page.locator('.stage .panel.card')).toHaveCount(3, { timeout: 45_000 });
    await page.waitForTimeout(1500);
    expect(await findCut(page)).toEqual([]);
    // As colunas do Painel rolam sozinhas: o que passa da altura da tela fica na rolagem, não cortado.
    if (!device.phone) for (const side of ['left', 'right']) await expect(page.locator(`.hud__${side}`)).toHaveCSS('overflow-y', 'auto');
    expect(errors).toEqual([]);
    await context.close();
  });
}

// ───────────────────────── Alto contraste ─────────────────────────

/** Cor "rgb(r g b / a)" ou "rgb(r, g, b)" do navegador, misturada com um fundo opaco. */
function luminance([r, g, b]: number[]): number {
  const channel = (value: number) => {
    const unit = value / 255;
    return unit <= 0.03928 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function hexToRgb(hex: string): number[] {
  return [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16));
}

/** Razão de contraste do texto (`--text-dim`, `--text-faint`...) sobre a parte mais clara do painel. */
async function textContrast(page: Page, token: string): Promise<number> {
  const { color, panel } = await page.evaluate((name) => {
    const probe = document.createElement('span');
    probe.style.color = `var(${name})`;
    document.body.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return { color, panel: getComputedStyle(document.documentElement).getPropertyValue('--panel-bg') };
  }, token);
  const numbers = (color.match(/[\d.]+/g) ?? []).map(Number);
  const [r, g, b] = numbers;
  const alpha = numbers.length > 3 ? numbers[3] : 1;
  // O painel das personas é um degradê de dois tons: vale o mais claro dos dois, o pior caso.
  const stops = (panel.match(/#[0-9a-f]{6}/gi) ?? ['#000000']).map(hexToRgb);
  const background = stops.reduce((best, stop) => (luminance(stop) > luminance(best) ? stop : best));
  const mixed = [r, g, b].map((value, index) => value * alpha + background[index] * (1 - alpha));
  const [light, dark] = [luminance(mixed), luminance(background)].sort((a, b2) => b2 - a);
  return (light + 0.05) / (dark + 0.05);
}

for (const theme of THEMES) {
  test(`o alto contraste vale na persona ${theme.label} sem perder a identidade dela`, async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    const errors = await openHud(page, theme.id);
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-contrast', 'normal');
    const normal = await page.evaluate(() => {
      const panel = document.querySelector('.panel')!;
      const style = getComputedStyle(panel);
      return {
        primary: getComputedStyle(document.documentElement).getPropertyValue('--c-primary-rgb').trim(),
        clip: style.clipPath,
        radius: style.borderRadius,
        font: getComputedStyle(document.querySelector('.panel__title')!).fontFamily,
        scanlines: getComputedStyle(document.querySelector('.fx--scanlines')!).display,
        background: style.backgroundImage,
      };
    });
    const faintBefore = await textContrast(page, '--text-faint');

    await page.keyboard.press('5');
    const group = page.getByRole('region', { name: 'Aparência' }).getByRole('radiogroup', { name: 'Alto contraste' });
    await expect(group.getByRole('radio', { name: /Automático/ })).toHaveAttribute('aria-checked', 'true');
    await group.getByRole('radio', { name: 'Ligado', exact: true }).click();
    await expect(html).toHaveAttribute('data-contrast', 'high');
    await expect(page.getByRole('region', { name: 'Aparência' })).toContainText('Alto contraste em uso');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('region', { name: 'Briefing' })).toBeVisible();
    await page.waitForTimeout(1000);

    const high = await page.evaluate(() => {
      const panel = document.querySelector('.panel')!;
      const style = getComputedStyle(panel);
      return {
        primary: getComputedStyle(document.documentElement).getPropertyValue('--c-primary-rgb').trim(),
        clip: style.clipPath,
        radius: style.borderRadius,
        font: getComputedStyle(document.querySelector('.panel__title')!).fontFamily,
        scanlines: getComputedStyle(document.querySelector('.fx--scanlines')!).display,
        sweep: getComputedStyle(document.querySelector('.fx--sweep')!).display,
        background: style.backgroundImage,
        backdrop: style.backdropFilter,
        shadow: style.boxShadow,
        borderColor: style.borderTopColor,
        textShadows: [...document.querySelectorAll('.panel__title, .brand__name, .clock__time')].map((el) => getComputedStyle(el).textShadow),
      };
    });
    // Sem scanlines, varredura, brilho nem desfoque; o painel é opaco e a borda é cheia.
    expect(high.scanlines).toBe('none');
    expect(high.sweep).toBe('none');
    expect(high.backdrop).toBe('none');
    expect(high.shadow).toBe('none');
    expect(high.textShadows.every((shadow) => shadow === 'none')).toBe(true);
    expect(high.background).not.toMatch(/rgba\(|\/ ?0?\.\d/);
    expect(high.borderColor).not.toMatch(/rgba\(|\/ ?0?\.\d/);
    // A identidade fica: a cor, o formato do painel e a fonte são os da persona.
    expect(high.primary).toBe(normal.primary);
    expect(high.clip).toBe(normal.clip);
    expect(high.radius).toBe(normal.radius);
    expect(high.font).toBe(normal.font);
    // E o texto menos forte passa do AAA (7:1) depois de ficar abaixo disso.
    const faint = await textContrast(page, '--text-faint');
    const dim = await textContrast(page, '--text-dim');
    expect(faint).toBeGreaterThan(faintBefore);
    expect(faint).toBeGreaterThanOrEqual(7);
    expect(dim).toBeGreaterThanOrEqual(7);
    expect(await textContrast(page, '--text')).toBeGreaterThanOrEqual(12);

    // Desligar volta ao que era (scanlines inclusas, nas personas que as têm).
    await page.keyboard.press('5');
    await page.getByRole('region', { name: 'Aparência' }).getByRole('radiogroup', { name: 'Alto contraste' }).getByRole('radio', { name: 'Desligado', exact: true }).click();
    await expect(html).toHaveAttribute('data-contrast', 'normal');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('region', { name: 'Briefing' })).toBeVisible();
    expect(await page.evaluate(() => getComputedStyle(document.querySelector('.fx--scanlines')!).display)).toBe(normal.scanlines);
    expect(errors).toEqual([]);
  });
}

test('o alto contraste fica salvo e a paleta de comandos liga, desliga e põe em automático', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const html = page.locator('html');
  const palette = page.getByRole('dialog', { name: 'Paleta de comandos' });
  const run = async (text: string, first: string) => {
    await page.keyboard.press('Control+k');
    await page.keyboard.type(text);
    await expect(palette.getByRole('option').first()).toContainText(first);
    await page.keyboard.press('Enter');
    await expect(palette).toHaveCount(0);
  };

  await run('alto contraste ligar', 'Alto contraste: ligar');
  await expect(html).toHaveAttribute('data-contrast', 'high');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('jarvis.hud.prefs') ?? '{}').contrast)).toBe('on');

  await page.reload();
  await page.locator('.boot').click();
  await expect(page.locator('.hud.hud--online')).toBeVisible();
  await expect(html).toHaveAttribute('data-contrast', 'high');

  await run('alto contraste desligar', 'Alto contraste: desligar');
  await expect(html).toHaveAttribute('data-contrast', 'normal');
  await run('alto contraste automatico', 'Alto contraste: automático');
  await expect(html).toHaveAttribute('data-contrast', 'normal');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('jarvis.hud.prefs') ?? '{}').contrast)).toBe('auto');
  expect(errors).toEqual([]);
});

test('em automático o alto contraste segue o pedido do sistema; a escolha da pessoa vale mais', async ({ page }) => {
  const errors = await openHud(page, 'jarvis');
  const html = page.locator('html');
  await expect(html).toHaveAttribute('data-contrast', 'normal');

  // O sistema pede mais contraste com o HUD aberto: vale na hora, sem recarregar.
  await page.emulateMedia({ contrast: 'more' });
  await expect(html).toHaveAttribute('data-contrast', 'high');
  await page.keyboard.press('5');
  const look = page.getByRole('region', { name: 'Aparência' });
  await expect(look).toContainText('Alto contraste em uso');

  // "Desligado" é uma escolha: o sistema não a desfaz.
  await look.getByRole('radio', { name: 'Desligado', exact: true }).click();
  await expect(html).toHaveAttribute('data-contrast', 'normal');
  await page.reload();
  await page.locator('.boot').click();
  await expect(page.locator('.hud.hud--online')).toBeVisible();
  await expect(html).toHaveAttribute('data-contrast', 'normal');

  // De volta ao automático, o pedido do sistema vale de novo; quando ele sai, o HUD volta ao normal.
  await page.keyboard.press('5');
  await page.getByRole('region', { name: 'Aparência' }).getByRole('radio', { name: /Automático/ }).click();
  await expect(html).toHaveAttribute('data-contrast', 'high');
  await page.emulateMedia({ contrast: 'no-preference' });
  await expect(html).toHaveAttribute('data-contrast', 'normal');
  expect(errors).toEqual([]);
});

test('o alto contraste não corta nada com o texto a 140%', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1280, height: 720 });
  await mockAreas(page);
  const errors = await openHud(page, 'mark3', { textSize: 140, contrast: 'on' });
  await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high');
  for (const { key, view } of VIEWS) {
    await goTo(page, key, view);
    expect(await findCut(page), `alto contraste, área ${view}`).toEqual([]);
  }
  expect(errors).toEqual([]);
});

// ───────────────────────── Teclado e leitor de tela ─────────────────────────

/** Tudo o que se clica ou digita e está à vista tem nome: texto, aria-label, rótulo ou título. */
async function unnamedControls(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const controls = document.querySelectorAll<HTMLElement>('main.app button, main.app a[href], main.app input, main.app select, main.app textarea, main.app [role="button"], main.app [role="radio"]');
    for (const el of controls) {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0 || getComputedStyle(el).visibility === 'hidden') continue;
      const labelled = el.getAttribute('aria-labelledby') ? document.getElementById(el.getAttribute('aria-labelledby')!)?.textContent?.trim() : '';
      const viaLabel = el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement ? [...(el.labels ?? [])].map((l) => l.textContent?.trim()).join('') : '';
      const name = el.getAttribute('aria-label')?.trim() || labelled || viaLabel || el.textContent?.trim() || '';
      if (!name) out.push(`${el.tagName.toLowerCase()}.${el.className}`);
    }
    return out;
  });
}

test('os botões só de ícone e os campos têm nome em todas as áreas', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await mockAreas(page);
  const errors = await openHud(page, 'jarvis');
  for (const { key, view } of VIEWS) {
    await goTo(page, key, view);
    expect(await unnamedControls(page), `área ${view}`).toEqual([]);
  }
  // Com resultados e aparelhos na tela, os botões repetidos dizem de quem são.
  await goTo(page, '3', 'eye');
  const devices = page.getByRole('region', { name: 'Aparelhos na rede' });
  await expect(devices).toBeVisible();
  await expect(devices.getByRole('button', { name: 'Esquecer Celular da Ana' })).toBeVisible();
  await expect(devices.getByRole('button', { name: 'Salvar o nome de Celular da Ana' })).toBeVisible();
  await expect(devices.getByRole('button', { name: /192\.168\.0\.50 é meu/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test('"Pular para o conteúdo" é o primeiro da tabulação e leva ao primeiro painel da área', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await mockAreas(page);
  const errors = await openHud(page, 'jarvis');
  const skip = page.getByRole('link', { name: 'Pular para o conteúdo' });
  // Fora de foco fica fora da tela; com o foco aparece.
  await expect(skip).not.toBeInViewport();
  await page.keyboard.press('Tab');
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();

  await goTo(page, '2', 'day');
  await skip.focus();
  await expect(skip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#conteudo')).toBeFocused();
  // O próximo Tab cai dentro da área: no primeiro controle do primeiro painel (Tarefas), não no topo.
  await page.keyboard.press('Tab');
  const inside = await page.evaluate(() => document.querySelector('#conteudo')?.contains(document.activeElement));
  expect(inside).toBe(true);
  await expect(page.getByRole('region', { name: 'Tarefas' }).locator(':focus')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('a ordem da tabulação no Dia a dia e no Olho de Deus segue a leitura da tela', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await mockAreas(page);
  const errors = await openHud(page, 'jarvis');
  // A ordem em que os controles recebem o foco: de cima para baixo e da esquerda para a direita,
  // coluna por coluna (cada coluna termina antes da seguinte começar).
  const order = async (view: string) => {
    return page.evaluate((selector) => {
      const area = document.querySelector(selector)!;
      const focusable = [...area.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href]')].filter(
        (el) => !(el as HTMLButtonElement).disabled && el.tabIndex >= 0 && el.getBoundingClientRect().width > 0,
      );
      const columns = [...area.querySelectorAll('.workspace__col')];
      const column = (el: HTMLElement) => columns.findIndex((col) => col.contains(el));
      return focusable.map((el) => ({ column: column(el), top: Math.round(el.getBoundingClientRect().top) }));
    }, `.workspace[data-view="${view}"]`);
  };
  for (const [key, view] of [['2', 'day'], ['3', 'eye']]) {
    await goTo(page, key, view);
    const stops = await order(view);
    expect(stops.length, `controles em ${view}`).toBeGreaterThan(4);
    // Nada de tabindex positivo bagunçando a ordem.
    expect(await page.evaluate(() => [...document.querySelectorAll('[tabindex]')].filter((el) => Number(el.getAttribute('tabindex')) > 0).length)).toBe(0);
    // Uma coluna só termina antes de a próxima começar.
    const columns = stops.map((stop) => stop.column);
    expect(columns).toEqual([...columns].sort((a, b) => a - b));
    // Dentro de cada coluna, de cima para baixo (o que está na mesma linha pode variar de largura).
    for (const column of new Set(columns)) {
      const tops = stops.filter((stop) => stop.column === column).map((stop) => stop.top);
      // Folga de 8 px: um campo e o botão ao lado dele não começam na mesma linha de pixels.
      expect(tops.every((top, index) => index === 0 || top >= tops[index - 1] - 8), `coluna ${column} em ${view}: ${tops}`).toBe(true);
    }
  }
  expect(errors).toEqual([]);
});

test('o foco do teclado aparece nos campos, botões e caixas de marcar do Dia a dia e do Olho de Deus', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await mockAreas(page);
  const errors = await openHud(page, 'mark3');
  const outline = (locator: ReturnType<Page['locator']>) =>
    locator.evaluate((el) => {
      const style = getComputedStyle(el);
      return { style: style.outlineStyle, width: parseFloat(style.outlineWidth) };
    });

  await goTo(page, '2', 'day');
  // Com o teclado em uso (uma tecla antes), o foco por código também conta como "visível".
  await page.keyboard.press('Tab');
  const tasks = page.getByRole('region', { name: 'Tarefas' });
  for (const control of [
    tasks.getByRole('checkbox').first(),
    tasks.getByRole('textbox', { name: 'Nova tarefa' }),
    tasks.getByRole('button', { name: /Apagar Ligar pro contador/ }),
    page.getByRole('region', { name: 'Foco' }).getByRole('button', { name: 'Começar o foco' }),
  ]) {
    await control.focus();
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    await expect(control).toBeFocused();
    const { style, width } = await outline(control);
    expect(style, await control.evaluate((el) => el.outerHTML.slice(0, 80))).not.toBe('none');
    expect(width).toBeGreaterThanOrEqual(2);
  }

  await goTo(page, '3', 'eye');
  await page.keyboard.press('Tab');
  for (const control of [
    page.getByRole('textbox', { name: 'O que consultar' }),
    page.getByRole('button', { name: 'IP', exact: true }),
    page.getByRole('textbox', { name: 'Senha para conferir em vazamentos' }),
  ]) {
    await control.focus();
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    await expect(control).toBeFocused();
    const { style, width } = await outline(control);
    expect(style).not.toBe('none');
    expect(width).toBeGreaterThanOrEqual(2);
  }
  expect(errors).toEqual([]);
});

test('o foco de um botão de forma recortada (clip-path) cai dentro da borda, onde não é cortado', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  const errors = await openHud(page, 'mark3');
  await page.keyboard.press('Tab');
  const button = page.getByRole('button', { name: 'Simulação' });
  await button.focus();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  await expect(button).toBeFocused();
  const focus = await button.evaluate((el) => {
    const style = getComputedStyle(el);
    return { clip: style.clipPath, offset: parseFloat(style.outlineOffset), width: parseFloat(style.outlineWidth), style: style.outlineStyle };
  });
  expect(focus.clip).not.toBe('none');
  expect(focus.style).not.toBe('none');
  expect(focus.width).toBeGreaterThanOrEqual(2);
  expect(focus.offset).toBeLessThan(0);
  expect(errors).toEqual([]);
});

test('os textos de status do Dia a dia e do Olho de Deus são avisados ao leitor de tela', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await mockAreas(page);
  const errors = await openHud(page, 'jarvis');

  await goTo(page, '2', 'day');
  // O resumo das tarefas, o estado da medição e o bloco do foco são regiões "status" (aria-live educado).
  await expect(page.getByRole('region', { name: 'Tarefas' }).getByRole('status')).toContainText('2 abertas');
  await expect(page.getByRole('region', { name: 'Foco' }).getByRole('status').first()).toHaveText('Foco parado.');
  // A contagem que anda a cada segundo não é anunciada.
  await expect(page.locator('.focus__time')).toHaveAttribute('aria-live', 'off');

  await goTo(page, '3', 'eye');
  const hint = page.locator('.eye__hint');
  await expect(hint).toHaveAttribute('aria-live', 'polite');
  await page.getByRole('textbox', { name: 'O que consultar' }).fill('8.8.8.8');
  await expect(hint).toContainText('Reconhecido como IP');
  await page.route('**/api/osint', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    await new Promise((done) => setTimeout(done, 2000));
    await route.fulfill({
      json: { kind: 'ip', label: 'IP', target: '8.8.8.8', title: '8.8.8.8', summary: 'Google', verdict: null, sections: [], lists: [], point: null, notes: [], sources: [], ts: 1_800_000_000 },
    });
  });
  await page.getByRole('button', { name: 'Consultar', exact: true }).click();
  await expect(hint).toHaveText('Consultando…');
  await expect(page.getByRole('status').filter({ hasText: '1 resultado nesta sessão' })).toBeVisible();

  // O topo diz em voz baixa o estado do link e do microfone.
  await expect(page.locator('.chips').getByRole('status')).toHaveText('Link inativo.');
  expect(errors).toEqual([]);
});
