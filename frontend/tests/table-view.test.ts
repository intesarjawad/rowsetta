import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { TablePage, WorkspaceState } from '../src/backend/types';
import LabelMenu from '../src/LabelMenu.svelte';
import { Studio } from '../src/state.svelte';
import TableView from '../src/TableView.svelte';
import { fakeBackend } from './fake-backend';

const STATE: WorkspaceState = {
  loaded: true,
  notice: null,
  target: 'species',
  classes: ['Adelie', 'Chinstrap', 'Gentoo'],
  human: { '100': 'Chinstrap' },
  eval_count: 0,
  threshold: 0.6,
  excluded_columns: [],
  generation: 6,
  refit_generation: 6,
  proposals: { '100': 'Adelie', '101': 'Gentoo', '102': 'Adelie' },
  confidence: { '100': 0.9, '101': 0.9, '102': 0.4 },
  abstained: [102],
  missing: {},
  next_row: 103,
  evaluation: null,
  failure: null,
  dev_states: false,
};

const PAGE: TablePage = {
  rows: [
    { species: null, island: 'Biscoe', bill_length_mm: 39.1 },
    { species: null, island: 'Dream', bill_length_mm: null },
    { species: null, island: 'Torgersen', bill_length_mm: 41.4 },
    { species: null, island: 'Biscoe', bill_length_mm: 38.6 },
  ],
  row_ids: [100, 101, 102, 103],
  columns: [
    {
      name: 'species',
      kind: 'categorical',
      distinct_ratio: 0.01,
      missing_ratio: 0,
    },
    {
      name: 'island',
      kind: 'categorical',
      distinct_ratio: 0.01,
      missing_ratio: 0,
    },
    {
      name: 'bill_length_mm',
      kind: 'numeric',
      distinct_ratio: 0.5,
      missing_ratio: 0.01,
    },
  ],
  total: 344,
  source_rows: 344,
  page: 1,
  size: 100,
};

async function studioWith(
  states: WorkspaceState[],
  page: TablePage | null = PAGE,
): Promise<Studio> {
  const studio = new Studio(
    fakeBackend([], {
      tablePage: () =>
        page === null
          ? Promise.reject(new Error('no page'))
          : Promise.resolve(page),
    }).backend,
  );
  for (const state of states) await studio.apply(Promise.resolve(state));
  if (page !== null) await studio.showPage(page.page);
  return studio;
}

function show(studio: Studio): string {
  return render(TableView, { props: { studio } }).body;
}

describe('table view', () => {
  it('renders a page as a real table with its position in the whole', async () => {
    const body = show(await studioWith([STATE]));

    expect(body).toContain('<table aria-rowcount="345"');
    expect(body).toContain('Rows 101 to 104 of 344');
    expect(body).toMatch(/<tr [^>]*aria-rowindex="1"/);
    expect(body).toMatch(
      /<tr [^>]*aria-rowindex="102"[^>]*><th scope="row"[^>]*>100</,
    );
    expect(body).toMatch(/<tr [^>]*aria-rowindex="105"/);
  });

  it('puts the target in the last column, as label cells, not as data', async () => {
    const body = show(await studioWith([STATE]));
    const headers = [...body.matchAll(/<th scope="col"[^>]*>([^<]*)</g)].map(
      (match) => match[1],
    );

    expect(headers).toEqual(['Row', 'island', 'bill length mm', 'species']);
  });

  it('leaves a missing value empty', async () => {
    const body = show(await studioWith([STATE]));

    expect(body).toMatch(/<td[^>]*>Dream<\/td>\s*<td[^>]*><\/td>/);
  });

  it('tells all four label states apart in text', async () => {
    const body = show(await studioWith([STATE]));

    expect(body).toContain('Labelled Chinstrap');
    expect(body).toContain('Proposed Gentoo');
    expect(body).toContain('Unsure');
    expect(body).toContain('Unlabelled');
    expect(body).not.toContain('Proposed Adelie');
  });

  it('marks proposals stale while a refit is pending', async () => {
    const body = show(
      await studioWith([STATE, { ...STATE, generation: 7, proposals: {} }]),
    );

    expect(body).toContain('Proposed Gentoo, updating');
    expect(body).toContain('Unsure, updating');
  });

  it('makes only the first label cell a tab stop', async () => {
    const body = show(await studioWith([STATE]));
    const stops = [...body.matchAll(/<button[^>]*tabindex="(-?\d)"/g)].map(
      (match) => match[1],
    );

    expect(stops).toEqual(['0', '-1', '-1', '-1']);
    expect(body).toContain('aria-haspopup="listbox"');
  });

  it('says which labels proposals still need', async () => {
    const body = show(
      await studioWith([
        { ...STATE, refit_generation: null, missing: { Gentoo: 2 } },
      ]),
    );

    expect(body).toContain('Proposals start after 2 more Gentoo.');
  });

  it('shows plain data and asks for a target before any labelling', async () => {
    const body = show(await studioWith([{ ...STATE, target: null }]));

    expect(body).toContain('Choose a target column to start labelling.');
    expect(body).toMatch(/<th scope="col"[^>]*>species<\/th>/);
    expect(body).not.toMatch(/<button[^>]*tabindex/);
  });

  it('shows refit progress, indeterminate until the row count is known', async () => {
    const studio = await studioWith([STATE]);
    studio.refit = { done: 0, total: null };
    expect(show(studio)).toContain(
      '<progress aria-label="Updating proposals"></progress>',
    );

    studio.refit = { done: 100, total: 338 };
    expect(show(studio)).toMatch(/<progress[^>]*max="338"[^>]*value="100"/);
  });

  it('disables the page buttons at either end', async () => {
    const firstPage = show(await studioWith([STATE], { ...PAGE, page: 0 }));
    const lastPage = show(await studioWith([STATE], { ...PAGE, page: 3 }));

    expect(firstPage).toMatch(
      /<button[^>]*disabled[^>]*aria-label="Previous page"/,
    );
    expect(firstPage).not.toMatch(/disabled[^>]*aria-label="Next page"/);
    expect(lastPage).toMatch(/<button[^>]*disabled[^>]*aria-label="Next page"/);
  });

  it('renders no table until a page arrives', async () => {
    const body = show(await studioWith([STATE], null));

    expect(body).not.toContain('<table');
  });
});

describe('label menu', () => {
  function menu(current: string | null): string {
    return render(LabelMenu, {
      props: {
        id: 'label-menu',
        rowId: 7,
        classes: ['Adelie', 'Chinstrap', 'Gentoo'],
        current,
        onpick: () => undefined,
        oncancel: () => undefined,
        onleave: () => undefined,
      },
    }).body;
  }

  it('is a labelled listbox with one option per class', () => {
    const body = menu(null);

    expect(body).toContain('role="listbox"');
    expect(body).toContain('aria-label="Label for row 7"');
    expect(body).toContain('aria-activedescendant="label-menu-0"');
    expect([...body.matchAll(/role="option"/g)]).toHaveLength(3);
    expect(body).not.toContain('Clear label');
  });

  it('offers to clear a human label', () => {
    const body = menu('Chinstrap');

    expect([...body.matchAll(/role="option"/g)]).toHaveLength(4);
    expect(body).toContain('Clear label');
  });
});

it('keeps distinct small numbers readable and numerically exact', async () => {
  const values = [1e-8, 1.2e-7, 1e-12, 1e-100];
  const studio = await studioWith([STATE], {
    ...PAGE,
    rows: values.map((x) => ({ bill_length_mm: x })),
  });
  const body = show(studio);
  for (const value of values) expect(body).toContain(String(value));
});

it('crosses out only labels that disagree with the suggested class', async () => {
  const studio = await studioWith([STATE]);
  const suspect = {
    row_id: 100,
    given: 'Chinstrap',
    likely: 'Chinstrap',
    given_probability: 0.999,
  };
  studio.suspects = [suspect];
  expect(show(studio)).not.toMatch(/class="[^"]*disagrees/);
  studio.suspects = [{ ...suspect, likely: 'Gentoo' }];
  expect(show(studio)).toMatch(/class="[^"]*disagrees/);
});
