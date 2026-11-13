import { expect, test, type Locator, type Page } from '@playwright/test';
import { openPenguins, openSetup } from './session';

async function labelSpeciesWithOneWrong(page: Page): Promise<Locator> {
  const cells = await openPenguins(page);
  await openSetup(page);
  await page.getByRole('radio', { name: /^species\b/ }).check();
  await page.getByRole('button', { name: 'Use its values as labels' }).click();
  await expect(cells.first()).toHaveText('Labelled Adelie');
  const relabel = await page.request.put('/labels/0', {
    data: { label: 'Gentoo', mode: 'human' },
  });
  expect(relabel.ok()).toBe(true);
  await page.reload();
  await expect(cells.first()).toHaveText('Labelled Gentoo');
  return cells;
}

test('the audit lists a wrong label first and the lens reads its row', async ({
  page,
}) => {
  await labelSpeciesWithOneWrong(page);

  await expect(page.getByRole('button', { name: /Fix all/ })).toHaveCount(0);
  const list = page.getByRole('list', { name: 'Labels the model doubts most' });
  const first = list.getByRole('listitem').first().getByRole('button').first();
  await expect(first).toContainText('Row 0', { timeout: 60_000 });
  await expect(first).toContainText('Gentoo to');

  // The most doubted row opens by itself; its button folds and unfolds it.
  await expect(first).toHaveAttribute('aria-expanded', 'true');
  await first.click();
  await expect(first).toHaveAttribute('aria-expanded', 'false');
  await first.click();
  const card = page.locator('#interchange .reading');
  await expect(card).toContainText(/Gentoo, it rides the \w+ line/);
  await expect(card.getByRole('button', { name: /^Change to / })).toBeVisible();
});

test('fixing a doubted label re-routes it onto its line', async ({ page }) => {
  const cells = await labelSpeciesWithOneWrong(page);

  const list = page.getByRole('list', { name: 'Labels the model doubts most' });
  const first = list.getByRole('listitem').first().getByRole('button').first();
  await expect(first).toContainText('Row 0', { timeout: 60_000 });
  await expect(first).toHaveAttribute('aria-expanded', 'true');
  const fix = page.getByRole('button', { name: /^Change to / });
  const likely = ((await fix.textContent()) ?? '').replace('Change to ', '');
  await fix.click();

  // The new label follows its line roundel, whose initial is part of the text.
  await expect(first).toContainText(`now ${likely.slice(0, 1)}${likely}`);
  await expect(cells.first()).toHaveText(`Labelled ${likely}`);
});
