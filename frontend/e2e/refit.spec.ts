import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import {
  labelByKeyboard,
  labelCells,
  openPenguins,
  openSetup,
  SLOW_REFIT_PORT,
  SLOW_E2E_TOKEN,
  TWO_PER_SPECIES,
} from './session';

const PENGUINS = readFileSync(
  new URL('../../src/rowsetta/datasets/penguins.csv', import.meta.url),
);
const SMALL = Buffer.from(
  `x,answer\n${Array.from({ length: 20 }, (_, i) => `${String(i)},${i > 0 && i < 10 ? 'a' : 'b'}`).join('\n')}\n`,
);
const SHOTS = process.env.ROWSETTA_FIX_SHOTS;

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS === undefined) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, name), fullPage: false });
}

async function openCsv(
  page: Page,
  name: string,
  buffer: Buffer,
): Promise<void> {
  await openSetup(page);
  await page
    .getByLabel('Choose or drop a CSV file')
    .setInputFiles({ name, mimeType: 'text/csv', buffer });
  await expect(page.locator('.appbar')).toContainText(name);
}

async function useColumn(page: Page, name: string): Promise<void> {
  await openSetup(page);
  await page.getByRole('radio', { name: new RegExp(`^${name}\\b`) }).check();
  await page.getByRole('button', { name: 'Use its values as labels' }).click();
  await expect(page.locator('details.setup')).not.toHaveAttribute('open');
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`restored penguins replaces the 20-row component cache at ${String(viewport.width)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openPenguins(page);
    await useColumn(page, 'species');
    const changed = await page.request.put('/labels/306', {
      data: { label: 'Gentoo', mode: 'human' },
    });
    expect(changed.ok()).toBe(true);
    await page.reload();
    await expect(page.locator('#interchange .doubts')).toBeVisible();
    await openCsv(page, 'twenty.csv', SMALL);
    await useColumn(page, 'answer');
    await expect(page.locator('#interchange .lede')).toContainText(
      '20 human labels',
    );
    await openCsv(page, 'penguins.csv', PENGUINS);
    await expect(page.locator('.appbar')).toContainText('target: species');
    const row = page
      .locator('#interchange .doubt > button')
      .filter({ hasText: 'Row 306' });
    await expect(row).toBeVisible();
    await expect(row).toHaveAttribute('aria-expanded', 'true');
    const reading = page.locator('#interchange .reading');
    await expect(reading.locator('dl')).toContainText('bill length');
    await expect(reading.locator('dl')).toContainText('40.9');
    await expect(
      reading.getByRole('button', { name: /Change to/ }),
    ).toBeVisible();
    await reading.scrollIntoViewIfNeeded();
    await shot(
      page,
      `stale-cache-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
    await page.evaluate(() => {
      window.scrollTo(0, 0);
    });
    await expect(page.locator('details.setup')).not.toHaveAttribute('open');
    expect(
      await page
        .locator('#interchange')
        .evaluate((el) => el.getBoundingClientRect().top),
    ).toBeLessThan(160);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(viewport.width);
    await shot(
      page,
      `post-setup-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
    await openSetup(page);
    await expect(page.getByLabel('New target name')).toBeVisible();
  });

  test(`dbt identifier errors stay in Export and SQL recovers at ${String(viewport.width)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await openPenguins(page);
    await openCsv(
      page,
      'risk.csv',
      Buffer.from(SMALL.toString().replace('answer', 'Risk category')),
    );
    await useColumn(page, 'Risk category');
    const panel = page.getByRole('region', { name: 'Export' });
    await expect(
      panel.getByRole('button', { name: 'Export rule' }),
    ).toBeEnabled();
    await panel.getByRole('button', { name: 'Export rule' }).click();
    await expect(panel.locator('pre')).toContainText('SELECT');
    await panel.getByRole('radio', { name: 'dbt', exact: true }).check();
    await expect(panel.getByRole('alert')).toContainText('identifier');
    await expect(page.locator('.appbar')).toContainText('model up to date');
    await expect(
      page.getByText('Browser runtime failed.', { exact: false }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Retry by reloading' }),
    ).toHaveCount(0);
    await panel.getByRole('alert').scrollIntoViewIfNeeded();
    await shot(
      page,
      `dbt-error-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
    await panel.getByRole('radio', { name: 'SQL', exact: true }).check();
    await expect(panel.getByRole('alert')).toHaveCount(0);
    await expect(panel.locator('pre')).toContainText('SELECT');
  });
}

test('audit waits for every class, retries failure after a label, and counts only audited humans', async ({
  page,
}) => {
  await openPenguins(page);
  let audits = 0;
  let releaseFailure: () => void = () => {};
  const heldFailure = new Promise<void>((resolve) => {
    releaseFailure = resolve;
  });
  await page.route('**/suspects', async (route) => {
    audits += 1;
    if (audits === 1) {
      await heldFailure;
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          error: 'Temporary audit failure.',
          next_step: 'Try checking labels again.',
        }),
      });
    } else await route.continue();
  });
  const cells = labelCells(page);
  await labelByKeyboard(page, cells, [
    '1',
    '1',
    '1',
    '1',
    '2',
    '2',
    '2',
    '3',
    '3',
    '3',
  ]);
  await expect(page.locator('#interchange')).toContainText(
    'Checking labels needs 1 more Adelie, 2 more Chinstrap, 2 more Gentoo',
  );
  expect(audits).toBe(0);
  for (const key of ['1', '2', '2', '3', '3']) {
    await page.keyboard.press(key);
    await page.keyboard.press('j');
  }
  await expect.poll(() => audits).toBe(1);
  await expect(page.locator('.appbar')).toContainText('model up to date');
  const failed = page.waitForResponse('**/suspects');
  releaseFailure();
  expect((await failed).status()).toBe(503);
  await expect(
    page.getByRole('button', { name: 'Check the labels', exact: true }),
  ).toBeEnabled();
  expect(audits).toBe(1);
  await page.keyboard.press('1');
  await page.keyboard.press('j');
  await expect(page.locator('#interchange .lede')).toContainText(
    '16 human labels',
  );
  expect(audits).toBe(2);
  await page.keyboard.press('1');
  await expect(
    page
      .getByRole('table')
      .locator('tbody tr')
      .nth(16)
      .getByRole('button', { name: 'Labelled Adelie', exact: true }),
  ).toBeVisible();
  await expect(page.locator('#interchange .lede')).toContainText(
    '16 human labels',
  );
  expect(audits).toBe(2);
  await expect(page.locator('#interchange .lede')).not.toContainText(
    'all 344 labels',
  );
});

test.describe('export during refit', () => {
  test.use({ baseURL: `http://127.0.0.1:${String(SLOW_REFIT_PORT)}` });
  test('Export remains disabled until refit completes', async ({ page }) => {
    const cells = await openPenguins(page, undefined, SLOW_E2E_TOKEN);
    await labelByKeyboard(page, cells, TWO_PER_SPECIES);
    const button = page.getByRole('button', { name: 'Export rule' });
    await expect(button).toBeDisabled();
    await expect(button).toBeEnabled({ timeout: 20_000 });
  });
});
