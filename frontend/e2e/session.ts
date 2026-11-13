import { expect, type Locator, type Page } from '@playwright/test';

/** The launch token both test servers accept; loopback only. */
export const E2E_TOKEN = 'e2e-only-token';
export const SLOW_E2E_TOKEN = 'e2e-slow-refit-token';

/** A second server whose fake teacher takes 1500 ms per prediction, so a refit is still running when the test acts. */
export const SLOW_REFIT_PORT = 8788;
export const SLOW_REFIT_DELAY_MS = 1500;

export const SPECIES = ['Adelie', 'Chinstrap', 'Gentoo'] as const;

export async function openSetup(page: Page): Promise<void> {
  const setup = page.locator('details.setup');
  if ((await setup.getAttribute('open')) === null)
    await setup.locator('summary').click();
}

/** The label buttons of the visible page, in row order. */
export function labelCells(page: Page): Locator {
  return page.getByRole('table').locator('tbody').getByRole('button');
}

/** Sign in, start a fresh labelling session on penguins `species`, and show the table. */
export async function openPenguins(
  page: Page,
  classes: readonly string[] = SPECIES,
  token = E2E_TOKEN,
): Promise<Locator> {
  await page.goto(`/?token=${token}`);
  // An earlier test may have opened another CSV on this server.
  const demo = await page.request.post('/table', {
    data: { demo: 'penguins' },
  });
  expect(demo.ok()).toBe(true);
  const response = await page.request.post('/target', {
    data: { target: 'species', classes },
  });
  expect(response.ok()).toBe(true);
  await page.reload();
  const cells = labelCells(page);
  await expect(cells.first()).toHaveText('Unlabelled');
  return cells;
}

/** Label the first rows by keyboard, one key per row, starting from the first cell. */
export async function labelByKeyboard(
  page: Page,
  cells: Locator,
  keys: readonly string[],
): Promise<void> {
  await cells.first().focus();
  for (const key of keys) {
    await page.keyboard.press(key);
    await page.keyboard.press('j');
  }
}

/** Two rows per species, the fewest that start proposals. */
export const TWO_PER_SPECIES = ['1', '1', '2', '2', '3', '3'] as const;
