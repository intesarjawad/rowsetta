import { describe, expect, it } from 'vitest';
import type { Backend } from '../src/backend/http';
import type {
  LabelInput,
  LeafLine,
  LeakHint,
  TablePage,
  TableQuery,
  WorkspaceState,
} from '../src/backend/types';
import { lineFilter } from '../src/rule';
import { Studio } from '../src/state.svelte';
import { fakeBackend } from './fake-backend';

const STATE: WorkspaceState = {
  loaded: true,
  notice: null,
  target: 'species',
  classes: ['Adelie', 'Chinstrap', 'Gentoo'],
  human: {},
  eval_count: 0,
  threshold: 0.6,
  excluded_columns: [],
  generation: 4,
  refit_generation: 4,
  proposals: {},
  confidence: {},
  abstained: [],
  missing: {},
  next_row: 250,
  evaluation: null,
  failure: null,
  dev_states: false,
};

const TOTAL_ROWS = 344;

// The server's pages of a 344-row table whose row ids are their positions.
function tablePage({ page, size }: TableQuery): Promise<TablePage> {
  const first = page * size;
  const rowIds = Array.from(
    { length: Math.max(Math.min(size, TOTAL_ROWS - first), 0) },
    (_, index) => first + index,
  );
  return Promise.resolve({
    rows: rowIds.map((rowId) => ({ island: `island ${String(rowId)}` })),
    row_ids: rowIds,
    columns: [],
    total: TOTAL_ROWS,
    source_rows: TOTAL_ROWS,
    page,
    size,
  });
}

async function studioOn(routes: Partial<Backend> = {}): Promise<Studio> {
  const studio = new Studio(fakeBackend([], { tablePage, ...routes }).backend);
  await studio.apply(Promise.resolve(STATE));
  await studio.showPage(0);
  return studio;
}

function line(lineNo: number, rowIds: readonly number[]): LeafLine {
  return {
    line_no: lineNo,
    conditions: [['flipper_length_mm', '>', '206.5']],
    label: 'Gentoo',
    row_ids: rowIds,
    agree: {
      k: rowIds.length,
      n: rowIds.length,
      coverage: { answered: rowIds.length, total: rowIds.length },
    },
  };
}

describe('evaluation mode', () => {
  it('serves a row, labels only that row, then serves the next', async () => {
    const served = [120, 7];
    const sent: [number, LabelInput][] = [];
    const studio = await studioOn({
      nextEvalRow: () => Promise.resolve(served.shift() ?? null),
      state: () => Promise.resolve({ ...STATE, eval_count: sent.length }),
      setLabel: (rowId, input) => {
        sent.push([rowId, input]);
        return Promise.resolve({ ...STATE, eval_count: sent.length });
      },
    });

    await studio.toggleEvaluation();
    expect(studio.mode).toEqual({ kind: 'evaluate', row: 120 });
    expect(studio.page?.page).toBe(1);
    expect(studio.focusRow).toBe(120);
    expect(studio.announcement?.text).toBe('Evaluation row 120');

    await studio.label(3, 'Adelie');
    expect(sent).toEqual([]);

    await studio.label(120, 'Gentoo');
    expect(sent).toEqual([[120, { label: 'Gentoo', mode: 'eval' }]]);
    expect(studio.mode).toEqual({ kind: 'evaluate', row: 7 });
    expect(studio.page?.page).toBe(0);
  });

  it('says so once every row has been served, and leaves on a second press', async () => {
    const studio = await studioOn({
      nextEvalRow: () => Promise.resolve(null),
    });

    await studio.toggleEvaluation();
    expect(studio.mode).toEqual({ kind: 'evaluate', row: null });
    expect(studio.announcement?.text).toBe(
      'Every row without a human label has been served.',
    );

    await studio.toggleEvaluation();
    expect(studio.mode).toEqual({ kind: 'label' });
  });
});

describe('jumping to a row', () => {
  it('focuses a row on the page already shown without fetching', async () => {
    const studio = await studioOn();

    await studio.goToRow(42);

    expect(studio.focusRow).toBe(42);
    expect(studio.page?.page).toBe(0);
  });

  it('goes to the page of the next suggested row', async () => {
    const studio = await studioOn();

    await studio.nextSuggested();

    expect(studio.page?.page).toBe(2);
    expect(studio.focusRow).toBe(250);
  });

  it('says when no row is left to suggest', async () => {
    const studio = await studioOn();
    await studio.apply(Promise.resolve({ ...STATE, next_row: null }));

    await studio.nextSuggested();

    expect(studio.announcement?.text).toBe(
      'No unlabelled row is left to suggest.',
    );
  });
});

describe('row filters', () => {
  it('shows only the filtered rows, announces them, and returns to the page before', async () => {
    const studio = await studioOn();
    await studio.showPage(3);
    const leaf = line(1, [5, 150, 301]);

    await studio.filterRows(lineFilter(leaf));
    expect(studio.page?.row_ids).toEqual([5, 150, 301]);
    expect(studio.page?.rows[1]).toEqual({ island: 'island 150' });
    expect(studio.page?.total).toBe(3);
    expect(studio.announcement?.text).toBe('Showing 3 rows for rule line 1');

    await studio.filterRows(null);
    expect(studio.filter).toBeNull();
    expect(studio.page?.page).toBe(3);
    expect(studio.page?.row_ids[0]).toBe(300);
  });

  it('fetches the whole table once, in the largest pages the server sends', async () => {
    const asked: TableQuery[] = [];
    const studio = await studioOn({
      tablePage: (query) => {
        asked.push(query);
        return tablePage(query);
      },
    });
    asked.length = 0;

    await studio.filterRows(lineFilter(line(1, [1])));
    await studio.filterRows(lineFilter(line(2, [2])));

    expect(asked).toEqual([{ page: 0, size: 1000 }]);
  });

  it('ignores the same line arriving twice, as focus and click do', async () => {
    const studio = await studioOn();
    const filter = lineFilter(line(1, [5]));
    await studio.filterRows(filter);
    studio.announcement = null;

    await studio.filterRows(lineFilter(line(1, filter.rowIds)));

    expect(studio.announcement).toBeNull();
  });
});

describe('leak hints', () => {
  const nameHint: LeakHint = {
    column: 'y_after',
    kind: 'name',
    reason: 'The name of `y_after` suggests an identifier or an outcome.',
    score: null,
  };

  it('keeps an excluded column listed after the audit stops reporting it', async () => {
    const audits = [[nameHint], []];
    const studio = await studioOn({
      audit: () => Promise.resolve(audits.shift() ?? []),
    });
    await studio.checkLeaks();
    expect(studio.leaks).toEqual([nameHint]);

    await studio.apply(
      Promise.resolve({
        ...STATE,
        generation: 5,
        excluded_columns: ['y_after'],
      }),
    );
    await studio.checkLeaks();

    expect(studio.leaks).toEqual([nameHint]);
  });

  it('drops a hint once its column is neither reported nor excluded', async () => {
    const audits = [[nameHint], []];
    const studio = await studioOn({
      audit: () => Promise.resolve(audits.shift() ?? []),
    });

    await studio.checkLeaks();
    await studio.checkLeaks();

    expect(studio.leaks).toEqual([]);
  });
});

describe('choosing a target', () => {
  it('sends the choice and forgets what belonged to the old labels', async () => {
    const sent: unknown[] = [];
    const studio = await studioOn({
      setTarget: (input) => {
        sent.push(input);
        return Promise.resolve({ ...STATE, generation: 5, target: 'urgent' });
      },
      distill: () =>
        Promise.resolve({ leaf_summary: [], disagreements: [], generation: 4 }),
    });
    await studio.showRule();
    await studio.filterRows(lineFilter(line(1, [5])));

    await studio.chooseTarget({ target: 'urgent', classes: ['yes', 'no'] });

    expect(sent).toEqual([{ target: 'urgent', classes: ['yes', 'no'] }]);
    expect(studio.workspace?.target).toBe('urgent');
    expect(studio.rule).toBeNull();
    expect(studio.filter).toBeNull();
  });

  it('counts the working rows from unfiltered pages only', async () => {
    const studio = await studioOn();

    await studio.filterRows(lineFilter(line(1, [5])));

    expect(studio.page?.total).toBe(1);
    expect(studio.rowCount).toBe(TOTAL_ROWS);
  });
});

describe('opening a CSV', () => {
  it('uploads it and shows its first page', async () => {
    const uploaded: string[] = [];
    const studio = await studioOn({
      uploadCsv: (file) => {
        uploaded.push(file.name);
        return Promise.resolve({ ...STATE, generation: 9, target: null });
      },
    });
    await studio.showPage(2);

    await studio.upload(new File(['x\n1\n'], 'bank_leak.csv'));

    expect(uploaded).toEqual(['bank_leak.csv']);
    expect(studio.workspace?.target).toBeNull();
    expect(studio.page?.page).toBe(0);
  });
});
