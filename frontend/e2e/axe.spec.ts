import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { TWO_PER_SPECIES, labelByKeyboard, openPenguins } from './session';

const BLOCKING_IMPACTS = new Set(['serious', 'critical']);

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`the labelling table has no serious or critical axe violations (motion: ${reducedMotion})`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion });
    const cells = await openPenguins(page);
    await labelByKeyboard(page, cells, TWO_PER_SPECIES);
    await expect(
      page.getByRole('status').filter({ hasText: 'Proposals updated' }),
    ).toHaveText('Proposals updated');
    // Scan with the label menu open, so the listbox is checked too.
    await page.keyboard.press('Enter');
    await expect(page.getByRole('listbox')).toBeFocused();

    const { violations } = await new AxeBuilder({ page }).analyze();
    const blocking = violations
      .filter((violation) => BLOCKING_IMPACTS.has(violation.impact ?? ''))
      .map(({ id, help, nodes }) => ({
        id,
        help,
        targets: nodes.map((node) => node.target),
      }));

    expect(blocking).toEqual([]);
  });
}
