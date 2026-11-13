import { expect, test } from '@playwright/test';
import {
  SLOW_REFIT_PORT,
  SLOW_E2E_TOKEN,
  TWO_PER_SPECIES,
  labelByKeyboard,
  openPenguins,
} from './session';

const PROPOSAL_OR_UNSURE = /^(Proposed (Adelie|Chinstrap|Gentoo)|Unsure)$/;

test.describe('keyboard labelling', () => {
  test('labels six penguin rows by keyboard and sees proposals', async ({
    page,
  }) => {
    const cells = await openPenguins(page);

    await labelByKeyboard(page, cells, TWO_PER_SPECIES);

    await expect(cells.nth(0)).toHaveText('Labelled Adelie');
    await expect(cells.nth(2)).toHaveText('Labelled Chinstrap');
    await expect(cells.nth(5)).toHaveText('Labelled Gentoo');
    await expect(
      page.getByRole('status').filter({ hasText: 'Proposals updated' }),
    ).toHaveText('Proposals updated');
    await expect(cells.nth(6)).toHaveText(PROPOSAL_OR_UNSURE);
    await expect(cells.nth(6)).toBeFocused();
  });

  test('0 picks the tenth class', async ({ page }) => {
    const classes = Array.from(
      { length: 10 },
      (_, index) => `Class ${String(index + 1)}`,
    );
    const cells = await openPenguins(page, classes);

    await cells.first().focus();
    await page.keyboard.press('0');

    await expect(cells.first()).toHaveText('Labelled Class 10');
  });

  test('u undoes the most recent label change', async ({ page }) => {
    const cells = await openPenguins(page);

    await labelByKeyboard(page, cells, ['2', '3']);
    await expect(cells.nth(1)).toHaveText('Labelled Gentoo');
    await page.keyboard.press('u');

    await expect(cells.nth(1)).toHaveText('Unlabelled');
    await expect(cells.nth(0)).toHaveText('Labelled Chinstrap');
  });

  test('k moves back up and the first row stays put', async ({ page }) => {
    const cells = await openPenguins(page);

    await cells.nth(1).focus();
    await page.keyboard.press('k');
    await expect(cells.nth(0)).toBeFocused();
    await page.keyboard.press('k');

    await expect(cells.nth(0)).toBeFocused();
  });

  test('the label menu is a listbox operated by arrows, Enter and Escape', async ({
    page,
  }) => {
    const cells = await openPenguins(page);

    await cells.first().focus();
    await page.keyboard.press('Enter');
    const menu = page.getByRole('listbox', { name: 'Label for row 0' });
    await expect(menu).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');

    await expect(menu).toBeHidden();
    await expect(cells.first()).toBeFocused();
    await expect(cells.first()).toHaveText('Labelled Gentoo');

    await page.keyboard.press('Enter');
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden();
    await expect(cells.first()).toBeFocused();
    await expect(cells.first()).toHaveText('Labelled Gentoo');

    await page.keyboard.press('Enter');
    await page.keyboard.press('End');
    await page.keyboard.press('Enter');
    await expect(cells.first()).toHaveText('Unlabelled');
  });

  test('the table pages through rows a hundred at a time', async ({ page }) => {
    await openPenguins(page);
    const table = page.getByRole('table');

    await expect(table.getByText('Rows 1 to 100 of 344')).toBeVisible();
    await page.getByRole('button', { name: 'Next page' }).click();

    await expect(table.getByText('Rows 101 to 200 of 344')).toBeVisible();
    await expect(table.getByRole('rowheader').first()).toHaveText('100');
  });
});

test.describe('during a slow refit', () => {
  test.use({ baseURL: `http://127.0.0.1:${String(SLOW_REFIT_PORT)}` });

  test('a keypress moves focus within 100 ms', async ({ page }) => {
    const cells = await openPenguins(page, undefined, SLOW_E2E_TOKEN);
    await labelByKeyboard(page, cells, TWO_PER_SPECIES);
    const refit = page.getByRole('progressbar', { name: 'Updating proposals' });
    await expect(refit).toBeVisible();

    await page.evaluate(() => {
      const timing = window as Window & { keyAt?: number; focusAt?: number };
      document.addEventListener(
        'keydown',
        () => {
          timing.keyAt = performance.now();
        },
        { capture: true, once: true },
      );
      document.addEventListener(
        'focusin',
        () => {
          timing.focusAt = performance.now();
        },
        { once: true },
      );
    });
    await page.keyboard.press('j');
    await expect(cells.nth(7)).toBeFocused();
    const elapsedMs = await page.evaluate(() => {
      const timing = window as Window & { keyAt?: number; focusAt?: number };
      if (timing.keyAt === undefined || timing.focusAt === undefined) {
        throw new Error('the key press or the focus change was not seen');
      }
      return timing.focusAt - timing.keyAt;
    });

    expect(elapsedMs).toBeLessThan(100);
    await expect(refit).toBeVisible();
  });
});
