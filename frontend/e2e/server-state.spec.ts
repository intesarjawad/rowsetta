import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import {
  E2E_TOKEN,
  SLOW_E2E_TOKEN,
  SLOW_REFIT_PORT,
  openPenguins,
  openSetup,
} from './session';

const LONG = readFileSync(new URL('./long-values.csv', import.meta.url));
const SHOTS = process.env.ROWSETTA_FIX_SHOTS;

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS === undefined) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, name), fullPage: false });
}

async function upload(page: Page, name: string, buffer: Buffer): Promise<void> {
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
  await expect(page.locator('.appbar')).toContainText('model up to date');
}

test('two launch cookies keep both servers authenticated', async ({
  page,
  context,
}) => {
  await page.goto(`/?token=${E2E_TOKEN}`);
  expect((await page.request.get('/state')).status()).toBe(200);
  const second = await context.newPage();
  await second.goto(
    `http://127.0.0.1:${String(SLOW_REFIT_PORT)}/?token=${SLOW_E2E_TOKEN}`,
  );
  expect((await page.request.get('/state')).status()).toBe(200);
  expect(
    (
      await second.request.get(
        `http://127.0.0.1:${String(SLOW_REFIT_PORT)}/state`,
      )
    ).status(),
  ).toBe(200);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Shortcuts' })).toBeVisible();
  await second.reload();
  await expect(second.getByRole('button', { name: 'Shortcuts' })).toBeVisible();
  await second.close();
});

test('successful uploads reset the target choice and reject an unselected column', async ({
  page,
}) => {
  await openPenguins(page);
  await upload(page, 'old.csv', Buffer.from('x,outcome\n1,a\n2,b\n3,a\n4,b\n'));
  await useColumn(page, 'outcome');
  await upload(page, 'new.csv', Buffer.from('x,answer\n1,a\n2,b\n3,a\n4,b\n'));
  const submit = page.getByRole('button', { name: 'Use its values as labels' });
  await expect(submit).toBeDisabled();
  await expect(page.locator('input[name="target-column"]:checked')).toHaveCount(
    0,
  );
  await useColumn(page, 'answer');
  await expect(page.locator('.appbar')).toContainText('target: answer');
  await page.reload();
  await expect(page.locator('.appbar .file')).toHaveText('new.csv');
  await page.getByRole('button', { name: 'Shortcuts' }).click();
  await expect(
    page.getByRole('button', { name: 'Close', exact: true }),
  ).toHaveClass('button');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`long audit fields, actions and SVG labels fit at ${String(viewport.width)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openPenguins(page);
    await upload(page, 'long-values.csv', LONG);
    await useColumn(page, 'outcome');
    const row = page.locator('#interchange .doubt > button').first();
    await expect(row).toBeVisible();
    await expect(row).toHaveAttribute('aria-expanded', 'true');
    const reading = page.locator('#interchange .reading');
    await expect(reading).toContainText(
      'Enterprise contract requiring manual verification',
    );
    await expect(
      reading.getByRole('button', { name: /Change to/ }),
    ).toBeVisible();
    await expect(reading.getByRole('button', { name: /Keep / })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(viewport.width);
    const overflow = await reading.evaluate((el) =>
      Array.from(el.querySelectorAll('dt, dd, button, strong'))
        .filter((node) => node.scrollWidth > node.clientWidth + 1)
        .map((node) => node.textContent),
    );
    expect(overflow).toEqual([]);
    const outside = await page
      .locator('#interchange svg.map, #interchange svg.strip')
      .evaluateAll((maps) =>
        maps.flatMap((map) => {
          const box = map.getBoundingClientRect();
          return Array.from(map.querySelectorAll('text'))
            .filter((label) => {
              const bounds = label.getBoundingClientRect();
              return bounds.left < box.left - 1 || bounds.right > box.right + 1;
            })
            .map((label) => label.textContent);
        }),
      );
    expect(outside).toEqual([]);
    await page.evaluate(() => {
      window.scrollTo(0, 0);
    });
    await shot(
      page,
      `long-values-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
    await reading.scrollIntoViewIfNeeded();
    await shot(
      page,
      `long-reading-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
  });
}

test('generation changes hide old SQL and certificate until regenerated', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPenguins(page);
  await openSetup(page);
  await useColumn(page, 'species');
  const panel = page.getByRole('region', { name: 'Export', exact: true });
  const generate = panel.getByRole('button', {
    name: 'Export rule',
    exact: true,
  });
  await generate.click();
  await expect(panel.locator('pre')).toContainText('SELECT');
  await expect(panel.getByRole('list', { name: 'Certificate' })).toBeVisible();
  await page.getByLabel('Confidence threshold').fill('1');
  await page.getByLabel('Confidence threshold').dispatchEvent('change');
  await expect(panel.locator('.alert[role="status"]')).toContainText('stale');
  await expect(panel.locator('pre')).toHaveCount(0);
  await expect(panel.getByRole('list', { name: 'Certificate' })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: /^Copy / })).toHaveCount(0);
  await expect(generate).toBeEnabled();
  await generate.click();
  await expect(panel.getByRole('list', { name: 'Certificate' })).toContainText(
    'Abstention threshold: 1.0',
  );
  const changed = await page.request.put('/labels/37', {
    data: { label: 'Chinstrap', mode: 'human' },
  });
  expect(changed.ok()).toBe(true);
  await expect(panel.locator('.alert[role="status"]')).toContainText('stale');
  await expect(generate).toBeEnabled();
  await panel.scrollIntoViewIfNeeded();
  await shot(page, 'stale-export-1440x900.png');
  await expect(panel.getByRole('button', { name: /^Copy / })).toHaveCount(0);
  await generate.click();
  await expect(panel.locator('pre')).toContainText('SELECT');
  const current = await page.request.get('/export?format=sql&dialect=duckdb');
  expect(await panel.locator('pre').textContent()).toBe(await current.text());
  await openSetup(page);
  await page.getByLabel('New target name').fill('decision');
  await page.getByLabel('Classes, separated by commas').fill('a,b');
  await page.getByRole('button', { name: 'Create target' }).click();
  await expect(panel.locator('.alert[role="status"]')).toContainText('stale');
  await expect(panel.locator('pre')).toHaveCount(0);
});
