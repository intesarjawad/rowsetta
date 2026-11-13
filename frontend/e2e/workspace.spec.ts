import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';
import type { Distilled, WorkspaceState } from '../src/backend/types';
import {
  TWO_PER_SPECIES,
  labelByKeyboard,
  labelCells,
  openPenguins,
  openSetup,
} from './session';

const BANK_LEAK = fileURLToPath(
  new URL('../../tests/fixtures/bank_leak.csv', import.meta.url),
);
const EVAL_ROWS = 20;
const CLASS_KEYS = ['1', '2', '3'] as const;

/** The row ids the table shows, in order. */
async function visibleRowIds(page: Page): Promise<number[]> {
  const headers = await page
    .getByRole('table')
    .locator('tbody')
    .getByRole('rowheader')
    .allTextContents();
  return headers.map(Number);
}

async function teachPenguins(page: Page): Promise<void> {
  const cells = await openPenguins(page);
  await labelByKeyboard(page, cells, TWO_PER_SPECIES);
  await expect(
    page.getByRole('status').filter({ hasText: 'Proposals updated' }),
  ).toHaveText('Proposals updated');
}

test.describe('table and target', () => {
  test('the drop zone explains which columns are used before a file is chosen', async ({
    page,
  }) => {
    await openPenguins(page);
    await openSetup(page);

    await expect(
      page.getByText(
        'Text columns inferred as free text are skipped when more than half of their values are distinct. Lower-cardinality text can remain a feature.',
      ),
    ).toBeVisible();
  });

  test('a column that copies the outcome is listed as a leak and Exclude strikes it', async ({
    page,
  }) => {
    await openPenguins(page);
    await openSetup(page);
    await page.getByLabel('Choose or drop a CSV file').setInputFiles(BANK_LEAK);
    await expect(page.getByText('Opened bank_leak.csv.')).toBeVisible();
    await expect(page.getByRole('table')).toContainText('of 5000');

    await page.getByRole('radio', { name: 'y (categorical)' }).check();
    await page
      .getByRole('button', { name: 'Use its values as labels' })
      .click();

    const leaks = page.getByRole('region', {
      name: 'Columns that may leak the answer',
    });
    const exclude = leaks.getByRole('button', {
      name: 'Exclude column y_after',
    });
    await expect(exclude).toBeVisible();
    await expect(leaks).toContainText('`y_after` alone predicts the label');
    await exclude.click();

    await expect(leaks.locator('s', { hasText: 'y_after' })).toBeVisible();
    await expect(
      leaks.getByRole('button', { name: 'Include column y_after' }),
    ).toBeVisible();
  });

  test('a new target starts with an empty labelled column', async ({
    page,
  }) => {
    const cells = await openPenguins(page);
    await openSetup(page);

    await page.getByLabel('New target name').fill('urgent');
    await page.getByLabel('Classes, separated by commas').fill('yes, no');
    await page.getByRole('button', { name: 'Create target' }).click();
    await expect(page.locator('details.setup')).not.toHaveAttribute('open');
    await openSetup(page);

    await expect(
      page.getByText('Target: urgent (yes, no). 0 human labels.'),
    ).toBeVisible();
    await expect(
      page.getByRole('columnheader', { name: 'urgent' }),
    ).toBeVisible();
    await expect(cells.first()).toHaveText('Unlabelled');
    await expect(
      page.getByText('Proposals start after 2 more yes'),
    ).toBeVisible();
  });

  test('an existing column pre-fills its labels until the user starts from scratch', async ({
    page,
  }) => {
    const cells = await openPenguins(page);
    await openSetup(page);

    await page.getByRole('radio', { name: /^species\b/ }).check();
    await page
      .getByRole('button', { name: 'Use its values as labels' })
      .click();

    await expect(page.locator('details.setup')).not.toHaveAttribute('open');
    await openSetup(page);
    await expect(
      page.getByText(
        'Took the labels from species; 0 rows with no value stay unlabelled.',
      ),
    ).toBeVisible();
    await expect(cells.first()).toHaveText('Labelled Adelie');
    await expect(page.getByText('344 human labels.')).toBeVisible();

    await page
      .getByRole('button', { name: 'Clear all and teach from scratch' })
      .click();

    await expect(page.locator('details.setup')).not.toHaveAttribute('open');
    await openSetup(page);
    await expect(cells.first()).toHaveText('Unlabelled');
    await expect(page.getByText('0 human labels.')).toBeVisible();
  });
});

test.describe('evaluation', () => {
  test('e serves a random row, other rows ignore clicks, and 20 labels give the figures', async ({
    page,
  }) => {
    await teachPenguins(page);
    const panel = page.getByRole('region', { name: 'Teacher accuracy' });
    const servedText = panel.getByText(/^Evaluating row \d+:/);
    const focusedRow = page
      .locator('tbody tr', { has: page.locator('button:focus') })
      .getByRole('rowheader');
    async function servedRow(): Promise<number> {
      const row = Number((await servedText.textContent())?.match(/\d+/)?.[0]);
      await expect(focusedRow).toHaveText(String(row));
      return row;
    }

    await page.keyboard.press('e');
    await expect(page.getByRole('status')).toHaveText(/^Evaluation row \d+$/);
    const served = await servedRow();

    const rowIds = await visibleRowIds(page);
    const other = labelCells(page).nth(rowIds.findIndex((id) => id !== served));
    await expect(other).toHaveAttribute('aria-disabled', 'true');
    // Playwright waits for aria-disabled elements to become enabled; the
    // click must still reach the row to show that it is ignored.
    await other.click({ force: true });
    await expect(page.getByRole('listbox')).toHaveCount(0);
    await labelCells(page).nth(rowIds.indexOf(served)).focus();

    for (let index = 0; index < EVAL_ROWS; index += 1) {
      const row = await servedRow();
      await page.keyboard.press(CLASS_KEYS[index % CLASS_KEYS.length] ?? '1');
      await expect(servedText).not.toHaveText(
        new RegExp(`^Evaluating row ${String(row)}:`),
      );
    }

    await expect(panel).toContainText(
      /20 evaluation rows\. Accuracy \d+% \(95% CI \d+% to \d+%\)\./,
    );
    await expect(panel).toContainText(
      /Balanced accuracy \d+% \(\d+% to \d+%\)\./,
    );
    await expect(panel).toContainText(/Always guessing \w+ would score \d+%\./);
    await page.keyboard.press('e');
    await expect(
      panel.getByRole('button', { name: 'Evaluate (e)' }),
    ).toBeVisible();
  });

  test('the unsure count follows the threshold slider', async ({ page }) => {
    await teachPenguins(page);
    const panel = page.getByRole('region', { name: 'Teacher accuracy' });
    const unsure = panel.getByText(/are marked unsure/);
    const slider = panel.getByLabel('Confidence threshold');
    // The server's count once the refit for this threshold has landed, as shown.
    async function shownUnsure(threshold: string): Promise<number> {
      let count = -1;
      await expect
        .poll(async () => {
          const response = await page.request.get('/state');
          const state = (await response.json()) as WorkspaceState;
          count =
            state.threshold === Number(threshold) &&
            state.refit_generation === state.generation
              ? state.abstained.length
              : -1;
          return count;
        })
        .toBeGreaterThanOrEqual(0);
      await expect(unsure).toContainText(
        `Threshold ${threshold}: ${String(count)} rows`,
      );
      return count;
    }

    await slider.fill('0.35');
    const low = await shownUnsure('0.35');
    await slider.fill('1');

    expect(await shownUnsure('1.00')).toBeGreaterThan(low);
  });
});

test.describe('table keys', () => {
  test('n focuses the next suggested row', async ({ page }) => {
    await teachPenguins(page);
    const response = await page.request.get('/state');
    const { next_row: next } = (await response.json()) as {
      next_row: number;
    };

    await page.keyboard.press('n');

    const focused = page.locator('tbody tr', {
      has: page.locator('button:focus'),
    });
    await expect(focused.getByRole('rowheader')).toHaveText(String(next));
  });

  test('? opens the key sheet and Escape gives focus back', async ({
    page,
  }) => {
    const cells = await openPenguins(page);
    await cells.first().focus();

    await page.keyboard.press('?');
    const sheet = page.getByRole('dialog', { name: 'Keyboard' });
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText('Jump to the next suggested row');
    await page.keyboard.press('Escape');

    await expect(sheet).toBeHidden();
    await expect(cells.first()).toBeFocused();
  });
});

async function showRule(page: Page): Promise<Distilled> {
  const distilled = page.waitForResponse('**/distill');
  await page.getByRole('button', { name: 'Export rule' }).click();
  // A resting pointer would filter by hovering whichever line appears under it.
  await page.mouse.move(0, 0);
  return (await (await distilled).json()) as Distilled;
}

test.describe('rule view', () => {
  test('focusing line 1 by keyboard shows its rows and Escape restores the page', async ({
    page,
  }) => {
    await teachPenguins(page);
    const pageBefore = await visibleRowIds(page);
    const rule = await showRule(page);
    const first = rule.leaf_summary[0];
    if (first === undefined) throw new Error('the rule has no lines');

    await page.getByRole('button', { name: 'Export rule' }).focus();
    await page.keyboard.press('Tab');

    const lineOne = page.getByRole('button', { name: /^Line 1:/ });
    await expect(lineOne).toBeFocused();
    await expect(page.getByRole('status')).toHaveText(
      `Showing ${String(first.row_ids.length)} rows for rule line 1`,
    );
    await expect
      .poll(() => visibleRowIds(page))
      .toEqual(first.row_ids.slice(0, 100));

    await page.keyboard.press('Escape');
    await expect.poll(() => visibleRowIds(page)).toEqual(pageBefore);
  });
});

test.describe('rule view on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('tapping a line shows its rows and Show all rows brings the page back', async ({
    page,
  }) => {
    await teachPenguins(page);
    const pageBefore = await visibleRowIds(page);
    const rule = await showRule(page);
    const last = rule.leaf_summary.at(-1);
    if (last === undefined) throw new Error('the rule has no lines');

    await page
      .getByRole('button', {
        name: new RegExp(`^Line ${String(last.line_no)}:`),
      })
      .tap();

    await expect
      .poll(() => visibleRowIds(page))
      .toEqual(last.row_ids.slice(0, 100));
    await page.getByRole('button', { name: 'Show all rows' }).tap();
    await expect.poll(() => visibleRowIds(page)).toEqual(pageBefore);
  });
});

/** Every row the table marks as disagreeing with the rule, paging through the whole table. */
async function disagreeingRowIds(page: Page): Promise<number[]> {
  const found: number[] = [];
  const next = page.getByRole('button', { name: 'Next page' });
  for (;;) {
    const rows = page
      .getByRole('table')
      .locator('tbody tr')
      .filter({ hasText: /Rule line \d+ disagrees/ });
    found.push(
      ...(await rows.getByRole('rowheader').allTextContents()).map(Number),
    );
    if (await next.isDisabled()) return found;
    const caption = await page
      .getByRole('table')
      .locator('caption')
      .textContent();
    await next.click();
    await expect(page.getByRole('table').locator('caption')).not.toHaveText(
      caption ?? '',
    );
  }
}

test.describe('export panel', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

  test('the copied SQL is the served export and the marked rows are the served disagreements', async ({
    page,
  }) => {
    await teachPenguins(page);
    const rule = await showRule(page);
    const sql = page.getByRole('region', { name: 'Export' }).locator('pre');
    await expect(sql).toContainText('rows identical');
    await expect(page.getByRole('list', { name: 'Certificate' })).toContainText(
      'Execution: DuckDB',
    );

    await page.getByRole('button', { name: 'Copy SQL' }).click();
    await expect(page.getByRole('status')).toHaveText('Copied SQL');
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    const served = await page.request.get('/export?format=sql&dialect=duckdb');
    expect(copied).toBe(await served.text());

    expect(rule.disagreements.length).toBeGreaterThan(0);
    expect((await disagreeingRowIds(page)).sort((a, b) => a - b)).toEqual(
      [...rule.disagreements].sort((a, b) => a - b),
    );
  });

  test('each format and dialect copies what the server exports for it', async ({
    page,
  }) => {
    await teachPenguins(page);
    await showRule(page);
    const shown = page.getByRole('region', { name: 'Export' }).locator('pre');
    await expect(shown).toContainText('rows identical');

    for (const [radio, format, dialect, copy] of [
      ['PostgreSQL', 'sql', 'postgres', 'Copy SQL'],
      ['Python', 'python', 'postgres', 'Copy Python'],
    ] as const) {
      const served = await (
        await page.request.get(`/export?format=${format}&dialect=${dialect}`)
      ).text();
      await page.getByRole('radio', { name: radio }).check();
      await expect(shown).toHaveText(served);
      await page.getByRole('button', { name: copy }).click();
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
        served,
      );
    }
    await expect(page.getByRole('radio', { name: 'PostgreSQL' })).toBeHidden();
  });
});

test('the confidence threshold starts at 0.60', async ({ page }) => {
  await teachPenguins(page);
  await expect(
    page.getByRole('slider', { name: 'Confidence threshold' }),
  ).toHaveValue('0.6');
  await expect(page.getByText(/^Threshold 0\.60:/)).toBeVisible();
});
