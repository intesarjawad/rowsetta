import { chromium, defineConfig } from '@playwright/test';

const port = process.env.ROWSETTA_BROWSER_PORT ?? '4173';
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e-browser',
  // This is a portability smoke; F18 startup budgets use headed Chromium separately.
  timeout: 120_000,
  expect: { timeout: 60_000 },
  workers: 1,
  use: { baseURL: origin, screenshot: 'only-on-failure' },
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
        headless: false,
        launchOptions: {
          args: ['--enable-unsafe-webgpu'],
          executablePath:
            process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ??
            (process.platform === 'darwin'
              ? '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
              : chromium.executablePath()),
        },
      },
    },
    { name: 'firefox', use: { browserName: 'firefox' } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
  webServer: {
    command: `uv run python -m http.server ${port} --bind 127.0.0.1 --directory site`,
    cwd: '..',
    url: origin,
    reuseExistingServer: false,
  },
});
