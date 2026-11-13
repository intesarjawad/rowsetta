import { expect, test } from '@playwright/test';
import { E2E_TOKEN, openSetup } from './session';

test('long target headers wrap and do not cover the submit button', async ({
  page,
}) => {
  await page.goto(`/?token=${E2E_TOKEN}`);
  const header = `long_${'x'.repeat(180)}`;
  await page.locator('input[type=file]').setInputFiles({
    name: 'long.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(`${header},other\na,x\nb,y\n`),
  });
  const choice = page.getByRole('radio', { name: new RegExp('^long') });
  await expect(choice).toBeAttached();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(width);
    await choice.check();
    await expect(
      page.getByRole('button', { name: 'Use its values as labels' }),
    ).toBeVisible();
  }
  await page.getByRole('button', { name: 'Use its values as labels' }).click();
  await expect(page.locator('details.setup')).not.toHaveAttribute('open');
  await openSetup(page);
  await expect(
    page.getByRole('main').getByText(`Target: ${header}`, { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText(`Took the labels from ${header}`, { exact: false }),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
});

test('connection failure offers a retry', async ({ page }) => {
  await page.route('**/events', (route) => route.abort());
  await page.goto(`/?token=${E2E_TOKEN}`);
  await expect(
    page.getByRole('status').filter({ hasText: 'Reconnecting' }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry now' })).toBeVisible();
});
