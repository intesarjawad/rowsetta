import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { test } from '@playwright/test';

test('TabICLv2 parity on an asserted headed WebGPU adapter', async ({}, testInfo) => {
  const output = testInfo.outputPath('parity.json');
  // The shared spike owns the headed browser and asserts both adapter and backend.
  const { stdout } = await promisify(execFile)(
    process.execPath,
    ['../scripts/browser_spike.mjs', output, '--assert'],
    {
      env: { ...process.env, PARITY_URL: 'http://127.0.0.1:5181' },
      timeout: 290_000,
    },
  );
  await testInfo.attach('measurements', {
    body: stdout,
    contentType: 'application/json',
  });
});
