import { defineConfig, devices } from '@playwright/test';

// Testes visuais do HUD (e2e/): o servidor de verdade em --no-agent entrega o web/dist já compilado.
const PORT = Number(process.env.JARVIS_E2E_PORT ?? 8123);

export default defineConfig({
  testDir: 'e2e',
  testMatch: '*.e2e.ts',
  // A persona fica no persona.json do servidor: um teste de cada vez.
  workers: 1,
  timeout: 60_000,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1600, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 900 } } }],
  webServer: {
    command: `${process.env.JARVIS_PYTHON ?? 'python'} jarvis.py --no-agent --no-browser --port ${PORT}`,
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/api/status`,
    timeout: 60_000,
    reuseExistingServer: false,
    stdout: 'pipe',
  },
});
