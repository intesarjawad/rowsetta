import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e-parity',
  outputDir: './test-results/parity',
  timeout: 300_000,
  workers: 1,
  webServer: {
    command: 'pnpm dev --port 5181 --force',
    url: 'http://127.0.0.1:5181/parity.html',
    reuseExistingServer: false,
  },
});
