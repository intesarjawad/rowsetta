import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import {
  TWO_PER_SPECIES,
  labelByKeyboard,
  openPenguins,
  openSetup,
} from './session';

const SHOTS = process.env.ROWSETTA_FIX_SHOTS;
async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS === undefined) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, name) });
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`first blind row stays hidden through its first render at ${String(viewport.width)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const cells = await openPenguins(page);
    await labelByKeyboard(page, cells, TWO_PER_SPECIES);
    await expect(page.locator('.appbar')).toContainText('model up to date');
    await expect(
      cells.filter({ hasText: /Proposed|Unsure/ }).first(),
    ).toBeVisible();
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route('**/state', async (route) => {
      await held;
      await route.continue();
    });
    await page.evaluate(() => {
      const observed: string[] = [];
      document.documentElement.dataset.blindLabels = JSON.stringify(observed);
      new MutationObserver(() => {
        for (const note of document.querySelectorAll('tbody .note')) {
          if (note.textContent !== 'Evaluation row: label it blind') continue;
          observed.push(
            note.parentElement?.querySelector('button')?.textContent ?? '',
          );
        }
        document.documentElement.dataset.blindLabels = JSON.stringify(observed);
      }).observe(document.querySelector('tbody') ?? document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    });
    try {
      await page
        .getByRole('button', { name: 'Evaluate (e)', exact: true })
        .click();
      const blind = page.locator('tr', {
        hasText: 'Evaluation row: label it blind',
      });
      await expect(blind).toBeVisible();
      await expect(blind.getByRole('button')).toHaveText('Unlabelled');
      await expect(blind).not.toContainText('disagrees');
      const rendered = JSON.parse(
        (await page.locator('html').getAttribute('data-blind-labels')) ?? '[]',
      ) as string[];
      expect(rendered.length).toBeGreaterThan(0);
      expect(rendered.every((text) => text === 'Unlabelled')).toBe(true);
      await shot(
        page,
        `blind-${String(viewport.width)}x${String(viewport.height)}.png`,
      );
    } finally {
      release();
    }
    await page.getByRole('button', { name: 'Stop evaluating (e)' }).click();
    await expect(
      page.locator('tr', { hasText: 'Evaluation row: label it blind' }),
    ).toHaveCount(0);
  });

  test(`keyboard label choices remain visible at ${String(viewport.width)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const cells = await openPenguins(page);
    await cells.first().click();
    const menu = page.getByRole('listbox');
    await expect(menu).toBeFocused();
    const colours = async () =>
      menu.getByRole('option').evaluateAll((options) =>
        options.map((option) => ({
          selected: option.getAttribute('aria-selected'),
          background: getComputedStyle(option).backgroundColor,
          colour: getComputedStyle(option).color,
        })),
      );
    await page.keyboard.press('ArrowDown');
    const active = menu.getByRole('option', { selected: true });
    await expect(active).toHaveText('Chinstrap');
    const styles = await colours();
    expect(styles[1]?.background).not.toBe(styles[0]?.background);
    expect(styles[1]?.colour).not.toBe(styles[0]?.colour);
    await shot(
      page,
      `menu-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
    await page.keyboard.press('Enter');
    await expect(cells.first()).toHaveText('Labelled Chinstrap');
  });

  test(`small numeric cells retain distinct values at ${String(viewport.width)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await openPenguins(page);
    await openSetup(page);
    const values = Array.from({ length: 12 }, (_, i) => (i + 1) / 1e8);
    await page.getByLabel('Choose or drop a CSV file').setInputFiles({
      name: 'small.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(`x\n${values.join('\n')}\n`),
    });
    const shown = page.locator('tbody tr td.num');
    await expect(shown).toHaveCount(values.length);
    expect((await shown.allTextContents()).map(Number)).toEqual(values);
    await page.getByRole('table').scrollIntoViewIfNeeded();
    await shot(
      page,
      `small-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
  });
}

test('agreeing audited labels keep their text intact', async ({ page }) => {
  await openPenguins(page);
  await openSetup(page);
  await page.getByLabel('Choose or drop a CSV file').setInputFiles({
    name: 'agreement.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      `x,outcome\n${Array.from({ length: 24 }, (_, i) => `${String(i < 12 ? i : i + 100)},${i < 12 ? 'no' : 'yes'}`).join('\n')}\n`,
    ),
  });
  await page.getByRole('radio', { name: /^outcome\b/ }).check();
  await page.getByRole('button', { name: 'Use its values as labels' }).click();
  await expect(page.locator('tbody tr.suspect').first()).toBeVisible();
  const labels = page.locator('tbody tr.suspect .word');
  expect(await labels.count()).toBeGreaterThan(0);
  expect(
    await labels.evaluateAll((nodes) =>
      nodes.map((node) => getComputedStyle(node).textDecorationLine),
    ),
  ).not.toContain('line-through');
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.getByRole('table').scrollIntoViewIfNeeded();
    await shot(
      page,
      `agreeing-${String(viewport.width)}x${String(viewport.height)}.png`,
    );
  }
});

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`map glass follows keyboard navigation and drag with motion ${reducedMotion}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion });
    await openPenguins(page);
    await openSetup(page);
    await page.getByRole('radio', { name: /^species\b/ }).check();
    await page
      .getByRole('button', { name: 'Use its values as labels' })
      .click();
    const map = page.getByRole('button', { name: /^Line map\./ });
    await expect(map).toBeVisible();
    const glass = page.locator('.loupe');
    await map.focus();
    await page.keyboard.press('Home');
    await expect(glass).not.toHaveClass(/away/);
    const origin = await glass.getAttribute('style');
    await page.keyboard.press('End');
    await expect(glass).not.toHaveAttribute('style', origin ?? '');
    await page.keyboard.press('Escape');
    await expect(glass).toHaveClass(/away/);
    await page.keyboard.press('ArrowUp');
    await expect(glass).not.toHaveClass(/away/);
    const handle = glass.locator('.handle');
    const rect = await handle.boundingBox();
    expect(rect).not.toBeNull();
    if (rect === null) throw new Error('Glass handle is missing');
    const before = await glass.getAttribute('style');
    await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      rect.x + rect.width / 2 - 40,
      rect.y + rect.height / 2 - 30,
      { steps: 5 },
    );
    await page.mouse.up();
    await expect(glass).not.toHaveAttribute('style', before ?? '');
    await shot(page, `glass-${reducedMotion}-1440x900.png`);
  });
}
