import { expect, test } from '@playwright/test';
import { openPenguins, openSetup } from './session';

for (const width of [1440, 390]) {
  test(`map, text and readings share the decimal boundary at ${String(width)}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.route('**/distill', async (route) => {
      const response = await route.fetch();
      const rule = (await response.json()) as { generation: number };
      await route.fulfill({
        json: {
          ...rule,
          leaf_summary: [
            {
              line_no: 1,
              conditions: [['bill_length_mm', '<', '48.80000114440918']],
              label: 'Adelie',
              row_ids: Array.from({ length: 172 }, (_, i) => i),
              agree: {
                k: 172,
                n: 172,
                coverage: { answered: 172, total: 172 },
              },
            },
            {
              line_no: 2,
              conditions: [['bill_length_mm', '>=', '48.80000114440918']],
              label: 'Gentoo',
              row_ids: Array.from({ length: 172 }, (_, i) => i + 172),
              agree: {
                k: 172,
                n: 172,
                coverage: { answered: 172, total: 172 },
              },
            },
          ],
        },
      });
    });
    await openPenguins(page);
    await openSetup(page);
    await page.getByRole('radio', { name: /^species\b/ }).check();
    await page
      .getByRole('button', { name: 'Use its values as labels' })
      .click();
    const rule = page.locator('section.rule');
    await expect(rule).toContainText('bill length ≤ 48.8');
    await expect(rule).toContainText('bill length > 48.8');
    await expect(rule).not.toContainText('48.80000114440918');
    const map = page.locator('svg.map');
    if (width === 1440) {
      await expect(map).toContainText('bill length 48.8 mm');
      await expect(map).not.toContainText('48.80000114440918');
    } else {
      const list = page.getByRole('list', {
        name: 'Labels the model doubts most',
      });
      await expect(list).toBeVisible();
      await list
        .getByRole('listitem')
        .first()
        .getByRole('button')
        .first()
        .click();
      await expect(list).toContainText(/bill length [≤>] 48\.8 mm/);
      await expect(list).not.toContainText('48.80000114440918');
    }
  });
}
