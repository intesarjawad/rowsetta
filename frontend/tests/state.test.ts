import { describe, expect, it } from 'vitest';
import { BackendError } from '../src/backend/http';
import type {
  LabelInput,
  TablePage,
  TableQuery,
  WorkspaceState,
} from '../src/backend/types';
import { NO_PROPOSALS } from '../src/labelling';
import { Studio } from '../src/state.svelte';
import { fakeBackend } from './fake-backend';

const BASE: WorkspaceState = {
  loaded: true,
  notice: null,
  target: 'species',
  classes: ['Adelie', 'Chinstrap', 'Gentoo'],
  human: {},
  eval_count: 0,
  threshold: 0.6,
  excluded_columns: [],
  generation: 1,
  refit_generation: null,
  proposals: {},
  confidence: {},
  abstained: [],
  missing: {},
  next_row: 0,
  evaluation: null,
  failure: null,
  dev_states: false,
};

function at(
  generation: number,
  refit_generation: number | null = null,
): WorkspaceState {
  return { ...BASE, generation, refit_generation };
}

const REJECTED = new BackendError(
  'rejected',
  {
    error: 'Proposals start once every class has 2 labels.',
    next_step: 'label 2 more rows of: Gentoo',
    missing: { Gentoo: 2 },
  },
  409,
);

interface Pending<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function pending<T>(): Pending<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

// Lets queued promise callbacks run.
function settled(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('following the server', () => {
  it.each(['labels', 'threshold', 'target'])(
    'invalidates an export and its certificate after changing %s',
    async (change) => {
      const studio = new Studio(fakeBackend([]).backend);
      await studio.apply(Promise.resolve(at(2, 2)));
      studio.exported = { format: 'sql', text: '-- old rule' };
      studio.certificate = ['old certificate'];
      await studio.apply(
        Promise.resolve({
          ...at(3, 2),
          ...(change === 'threshold' ? { threshold: 1 } : {}),
          ...(change === 'target' ? { target: 'answer' } : {}),
        }),
      );
      expect(studio.exported).toBeNull();
      expect(studio.certificate).toEqual([]);
      await studio.apply(Promise.resolve(at(3, 3)));
      expect(studio.exported).toBeNull();
      expect(studio.certificate).toEqual([]);
    },
  );

  it('keeps dbt operation errors separate from model health and recovers with SQL', async () => {
    const error = {
      error: 'Invalid dbt identifier: Risk category',
      next_step: 'Choose SQL or Python.',
    };
    const studio = new Studio(
      fakeBackend([], {
        exportRule: (query) =>
          query.format === 'dbt'
            ? Promise.reject(new BackendError('rejected', error, 400))
            : Promise.resolve({ format: 'sql', text: '-- SQL' }),
      }).backend,
    );
    await studio.apply(Promise.resolve(at(2, 2)));
    await studio.showExport({ format: 'dbt', dialect: 'duckdb' });
    expect(studio.exportProblem).toEqual(error);
    expect(studio.problem).toBeNull();
    expect(studio.workspace?.failure).toBeNull();
    await studio.showExport({ format: 'sql', dialect: 'duckdb' });
    expect(studio.exportProblem).toBeNull();
    expect(studio.exported).toEqual({ format: 'sql', text: '-- SQL' });
  });

  it('does not request an export or distillation during refit', async () => {
    let requests = 0;
    const studio = new Studio(
      fakeBackend([], {
        distill: () => {
          requests += 1;
          return Promise.resolve({
            generation: 2,
            leaf_summary: [],
            disagreements: [],
          });
        },
        exportRule: () => {
          requests += 1;
          return Promise.resolve({ format: 'sql', text: '-- SQL' });
        },
      }).backend,
    );
    await studio.apply(Promise.resolve(at(2, 1)));
    await studio.exportRule(4);
    await studio.showExport({ format: 'sql', dialect: 'duckdb' });
    expect(requests).toBe(0);
  });
  it('loads the state once the event stream connects', async () => {
    const server = fakeBackend([() => Promise.resolve(at(1))]);
    const studio = new Studio(server.backend);

    studio.start();
    expect(studio.connection).toBe('connecting');
    expect(studio.workspace).toBeNull();

    server.send({ kind: 'connected' });
    await settled();

    expect(studio.connection).toBe('live');
    expect(studio.workspace).toEqual(at(1));
  });

  it('stops following when the returned function is called', () => {
    const server = fakeBackend([]);
    const stop = new Studio(server.backend).start();

    stop();

    expect(server.stopped()).toBe(true);
  });

  it('shows refit progress, then refetches the state when the refit lands', async () => {
    const server = fakeBackend([
      () => Promise.resolve(at(2)),
      () => Promise.resolve(at(2, 2)),
    ]);
    const studio = new Studio(server.backend);
    studio.start();
    server.send({ kind: 'connected' });
    await settled();

    server.send({ kind: 'refit_started', generation: 2 });
    expect(studio.refit).toEqual({ done: 0, total: null });
    server.send({ kind: 'progress', done: 100, total: 338 });
    expect(studio.refit).toEqual({ done: 100, total: 338 });
    server.send({ kind: 'refit_done', generation: 2 });
    await settled();

    expect(studio.refit).toBeNull();
    expect(studio.workspace).toEqual(at(2, 2));
  });

  it('refetches the state after a failed refit so its failure shows', async () => {
    const failure = {
      error: 'The model file is missing or failed its checksum.',
      next_step: 'rowsetta doctor --fix',
    };
    const server = fakeBackend([
      () => Promise.resolve(at(2)),
      () => Promise.resolve({ ...at(2), failure }),
    ]);
    const studio = new Studio(server.backend);
    studio.start();
    server.send({ kind: 'connected' });
    await settled();

    server.send({ kind: 'refit_started', generation: 2 });
    server.send({ kind: 'refit_failed', failure });
    await settled();

    expect(studio.refit).toBeNull();
    expect(studio.workspace?.failure).toEqual(failure);
  });

  it('marks a dropped stream and resynchronises with a restarted server', async () => {
    const server = fakeBackend([
      () => Promise.resolve(at(9, 9)),
      () => Promise.resolve(at(0)),
    ]);
    const studio = new Studio(server.backend);
    studio.start();
    server.send({ kind: 'connected' });
    await settled();

    server.send({ kind: 'disconnected', retryMs: 1000 });
    expect(studio.connection).toBe('reconnecting');
    server.send({ kind: 'connected' });
    await settled();

    expect(studio.connection).toBe('live');
    expect(studio.workspace).toEqual(at(0));
  });

  it('shows a broken event stream as a runtime failure', () => {
    const server = fakeBackend([]);
    const studio = new Studio(server.backend);
    studio.start();
    const failure = {
      error:
        'The local server sent an unexpected response (progress.done: expected an integer).',
      next_step: 'Reload this page; if it repeats, reinstall rowsetta.',
    };

    server.send({ kind: 'malformed', failure });

    expect(studio.runtimeFailure).toEqual(failure);
    expect(studio.problem).toBeNull();
  });
});

describe('applying responses', () => {
  it('keeps a newer state when an older response arrives late', async () => {
    const studio = new Studio(fakeBackend([]).backend);
    const slow = pending<WorkspaceState>();
    const fast = pending<WorkspaceState>();

    const first = studio.apply(slow.promise);
    const second = studio.apply(fast.promise);
    fast.resolve(at(3));
    await second;
    slow.resolve(at(2));
    await first;

    expect(studio.workspace).toEqual(at(3));
  });

  it('keeps a finished refit when the response that queued it arrives after', async () => {
    const queued = pending<WorkspaceState>();
    const studio = new Studio(
      fakeBackend([], { setTarget: () => queued.promise }).backend,
    );

    const chosen = studio.chooseTarget({ target: 'species', classes: ['a'] });
    await studio.apply(Promise.resolve(at(3, 3)));
    queued.resolve(at(3));
    await chosen;

    expect(studio.workspace).toEqual(at(3, 3));
  });

  it('takes a later refit of the same inputs', async () => {
    const studio = new Studio(fakeBackend([]).backend);

    await studio.apply(Promise.resolve(at(3, 2)));
    await studio.apply(Promise.resolve(at(3, 3)));
    await studio.apply(Promise.resolve(at(3)));

    expect(studio.workspace).toEqual(at(3, 3));
  });

  it('takes an equal state, which can differ in served evaluation rows', async () => {
    const studio = new Studio(fakeBackend([]).backend);
    const served = { ...at(3, 3), next_row: 41 };

    await studio.apply(Promise.resolve(at(3, 3)));
    await studio.apply(Promise.resolve(served));

    expect(studio.workspace).toEqual(served);
  });

  it('keeps the last state and shows the error contract when a request is refused', async () => {
    const studio = new Studio(fakeBackend([]).backend);
    await studio.apply(Promise.resolve(at(1)));

    await studio.apply(Promise.reject(REJECTED));

    expect(studio.workspace).toEqual(at(1));
    expect(studio.problem).toEqual(REJECTED.body);
  });

  it('clears the problem once a request succeeds', async () => {
    const studio = new Studio(fakeBackend([]).backend);
    await studio.apply(Promise.reject(REJECTED));

    await studio.apply(Promise.resolve(at(2)));

    expect(studio.problem).toBeNull();
  });

  it('lets a programming error propagate', async () => {
    const studio = new Studio(fakeBackend([]).backend);
    const bug = new TypeError('undefined is not a function');

    await expect(studio.apply(Promise.reject(bug))).rejects.toBe(bug);
    expect(studio.problem).toBeNull();
  });

  it('refreshes from /state on request', async () => {
    const server = fakeBackend([() => Promise.resolve(at(5))]);
    const studio = new Studio(server.backend);

    await studio.refresh();

    expect(studio.workspace).toEqual(at(5));
    expect(server.remaining()).toBe(0);
  });
});

describe('labelling', () => {
  it('sends a label and shows the state it returns', async () => {
    const sent: [number, LabelInput][] = [];
    const studio = new Studio(
      fakeBackend([], {
        setLabel: (rowId, input) => {
          sent.push([rowId, input]);
          return Promise.resolve(at(2));
        },
      }).backend,
    );

    await studio.label(3, 'Gentoo');
    await studio.label(3, null);

    expect(sent).toEqual([
      [3, { label: 'Gentoo' }],
      [3, { label: null }],
    ]);
    expect(studio.workspace).toEqual(at(2));
  });

  it('undoes the most recent change', async () => {
    let undone = 0;
    const studio = new Studio(
      fakeBackend([], {
        undo: () => {
          undone += 1;
          return Promise.resolve(at(4));
        },
      }).backend,
    );

    await studio.undo();

    expect(undone).toBe(1);
    expect(studio.workspace).toEqual(at(4));
  });

  it('shows a refused label as the problem and keeps the last state', async () => {
    const studio = new Studio(
      fakeBackend([], { setLabel: () => Promise.reject(REJECTED) }).backend,
    );
    await studio.apply(Promise.resolve(at(1)));

    await studio.label(3, 'Gentoo');

    expect(studio.workspace).toEqual(at(1));
    expect(studio.problem).toEqual(REJECTED.body);
  });
});

describe('proposals', () => {
  const fitted: WorkspaceState = {
    ...at(6, 6),
    proposals: { '7': 'Gentoo' },
    abstained: [8],
  };

  it('keeps the last proposals, marked stale, until the refit lands', async () => {
    const studio = new Studio(fakeBackend([]).backend);

    await studio.apply(Promise.resolve(fitted));
    expect(studio.proposals.stale).toBe(false);
    await studio.apply(Promise.resolve(at(7, 6)));

    expect(studio.proposals).toEqual({
      target: 'species',
      labels: { '7': 'Gentoo' },
      unsure: new Set([8]),
      stale: true,
    });
  });

  it('ignores the proposals of a state a newer one overtook', async () => {
    const studio = new Studio(fakeBackend([]).backend);

    await studio.apply(Promise.resolve(at(7)));
    await studio.apply(Promise.resolve(fitted));

    expect(studio.proposals).toEqual({ ...NO_PROPOSALS, target: 'species' });
  });

  it('announces proposals that a refit published', async () => {
    const studio = new Studio(fakeBackend([]).backend);
    await studio.apply(Promise.resolve(at(5, 4)));
    expect(studio.announcement).toBeNull();

    await studio.apply(Promise.resolve(fitted));

    expect(studio.announcement).toEqual({ text: 'Proposals updated' });
  });

  it('announces each refit again, so a screen reader repeats the same words', async () => {
    const studio = new Studio(fakeBackend([]).backend);
    await studio.apply(Promise.resolve(at(5, 4)));
    await studio.apply(Promise.resolve(fitted));
    const first = studio.announcement;

    await studio.apply(Promise.resolve(at(7, 6)));
    expect(studio.announcement).toBe(first);
    await studio.apply(Promise.resolve(at(7, 7)));

    expect(studio.announcement).toEqual(first);
    expect(studio.announcement).not.toBe(first);
  });

  it('does not announce the proposals already there when the page opens', async () => {
    const studio = new Studio(fakeBackend([]).backend);

    await studio.apply(Promise.resolve(fitted));

    expect(studio.announcement).toBeNull();
  });
});

describe('table pages', () => {
  function page(index: number): TablePage {
    return {
      rows: [{ island: 'Biscoe', species: null }],
      row_ids: [index * 100],
      columns: [],
      total: 344,
      source_rows: 344,
      page: index,
      size: 100,
    };
  }

  it('asks for 100 rows of the requested page', async () => {
    const asked: TableQuery[] = [];
    const studio = new Studio(
      fakeBackend([], {
        tablePage: (query) => {
          asked.push(query);
          return Promise.resolve(page(query.page));
        },
      }).backend,
    );

    await studio.showPage(2);

    expect(asked).toEqual([{ page: 2, size: 100 }]);
    expect(studio.page).toEqual(page(2));
  });

  it('keeps the latest requested page when an earlier one answers late', async () => {
    const slow = pending<TablePage>();
    const studio = new Studio(
      fakeBackend([], {
        tablePage: ({ page: index }) =>
          index === 0 ? slow.promise : Promise.resolve(page(index)),
      }).backend,
    );

    const first = studio.showPage(0);
    await studio.showPage(1);
    slow.resolve(page(0));
    await first;

    expect(studio.page).toEqual(page(1));
  });

  it('shows a refused page request as the problem', async () => {
    const studio = new Studio(
      fakeBackend([], { tablePage: () => Promise.reject(REJECTED) }).backend,
    );

    await studio.showPage(0);

    expect(studio.page).toBeNull();
    expect(studio.problem).toEqual(REJECTED.body);
  });
});

describe('workspace request isolation', () => {
  const page: TablePage = {
    rows: [{ x: 1 }],
    row_ids: [0],
    columns: [],
    total: 1,
    source_rows: 1,
    page: 0,
    size: 100,
  };

  it('keeps the entire previous view after a rejected upload or target', async () => {
    const studio = new Studio(
      fakeBackend([], {
        uploadCsv: () => Promise.reject(REJECTED),
        setTarget: () => Promise.reject(REJECTED),
      }).backend,
    );
    await studio.apply(Promise.resolve(at(2)));
    studio.fileName = 'previous.csv';
    studio.page = page;
    studio.rowCount = 1;
    studio.suspects = [];
    studio.kept = new Set([0]);
    await studio.upload(new File(['x\n'], 'invalid.csv'));
    expect(studio.fileName).toBe('previous.csv');
    expect(studio.page).toBe(page);
    expect(studio.rowCount).toBe(1);
    expect(studio.suspects).toEqual([]);
    expect(studio.kept.has(0)).toBe(true);
    await studio.chooseTarget({ target: 'invalid', classes: ['a', 'b'] });
    expect(studio.kept.has(0)).toBe(true);
    expect(studio.workspace).toEqual(at(2));
  });

  it.each(['upload', 'target', 'generation'] as const)(
    'discards late audit, rule, export and page results after %s',
    async (change) => {
      const suspects = pending<import('../src/backend/types').Suspect[]>();
      const leaks = pending<import('../src/backend/types').LeakHint[]>();
      const rule = pending<import('../src/backend/types').Distilled>();
      const artifact = pending<import('../src/backend/types').ExportArtifact>();
      const oldPage = pending<TablePage>();
      let pages = 0;
      const studio = new Studio(
        fakeBackend([], {
          suspects: () => suspects.promise,
          audit: () => leaks.promise,
          distill: () => rule.promise,
          exportRule: () => artifact.promise,
          tablePage: () =>
            ++pages === 1 ? oldPage.promise : Promise.resolve(page),
          uploadCsv: () => Promise.resolve({ ...at(3), target: null }),
          setTarget: () => Promise.resolve({ ...at(3), target: 'new' }),
        }).backend,
      );
      await studio.apply(Promise.resolve(at(2)));
      const requests = [
        studio.checkLabels(),
        studio.checkLeaks(),
        studio.showRule(),
        studio.showExport({ format: 'sql', dialect: 'duckdb' }),
        studio.showPage(0),
      ];
      if (change === 'upload')
        await studio.upload(new File(['x\n1\n'], 'new.csv'));
      else if (change === 'target')
        await studio.chooseTarget({ target: 'new', classes: ['a', 'b'] });
      else await studio.apply(Promise.resolve(at(3)));
      suspects.resolve([
        { row_id: 271, given: 'a', likely: 'b', given_probability: 0 },
      ]);
      leaks.resolve([]);
      rule.resolve({ generation: 2, leaf_summary: [], disagreements: [271] });
      artifact.resolve({ format: 'sql', text: '-- old dataset\nSELECT 1;' });
      oldPage.resolve({ ...page, row_ids: [271] });
      await Promise.all(requests);
      expect(studio.suspects).toBeNull();
      expect(studio.rule).toBeNull();
      expect(studio.exported).toBeNull();
      expect(studio.certificate).toEqual([]);
      expect(studio.page?.row_ids ?? []).not.toContain(271);
    },
  );
});

it('replaces an in-flight whole-table read after a successful upload', async () => {
  const old = pending<TablePage>();
  let reads = 0;
  const newPage: TablePage = {
    rows: [{ x: 12 }],
    row_ids: [0],
    columns: [],
    total: 1,
    source_rows: 1,
    page: 0,
    size: 100,
  };
  const studio = new Studio(
    fakeBackend([], {
      tablePage: () => (++reads === 1 ? old.promise : Promise.resolve(newPage)),
      uploadCsv: () => Promise.resolve({ ...at(3), target: null }),
    }).backend,
  );
  await studio.apply(Promise.resolve(at(2)));
  const whole = studio.wholeTable();
  await studio.upload(new File(['x\n12\n'], 'new.csv'));
  old.resolve({ ...newPage, row_ids: [271], rows: [{ x: 999 }] });
  const result = await whole;
  expect(result.rowIds).toEqual([0]);
  expect(result.rows.get(0)).toEqual({ x: 12 });
  expect(await studio.wholeTable()).toBe(result);
});

it('masks the first reserved row before navigation and state refresh finish', async () => {
  const refreshed = pending<WorkspaceState>();
  const studio = new Studio(
    fakeBackend([() => refreshed.promise], {
      nextEvalRow: () => Promise.resolve(7),
      tablePage: () =>
        Promise.resolve({
          rows: [],
          row_ids: [7],
          columns: [],
          total: 1,
          source_rows: 1,
          page: 0,
          size: 100,
        }),
    }).backend,
  );
  const state = {
    ...at(2, 2),
    proposals: { '7': 'Gentoo' },
    confidence: { '7': 0.9 },
    abstained: [7],
  };
  await studio.apply(Promise.resolve(state));
  const serving = studio.toggleEvaluation();
  await settled();
  expect(studio.mode).toEqual({ kind: 'evaluate', row: 7 });
  expect(studio.proposals.labels['7']).toBeUndefined();
  expect(studio.proposals.unsure.has(7)).toBe(false);
  expect(studio.workspace?.proposals['7']).toBeUndefined();
  expect(studio.workspace?.confidence['7']).toBeUndefined();
  refreshed.resolve(state);
  await serving;
  expect(studio.proposals.labels['7']).toBeUndefined();
  await studio.toggleEvaluation();
  await studio.apply(Promise.resolve({ ...state, refit_generation: 1 }));
  expect(studio.proposals.labels['7']).toBeUndefined();
});

it('waits for every table page before exposing rule precision', async () => {
  const last = pending<TablePage>();
  const page: TablePage = {
    rows: [{ x: 1 }],
    row_ids: [0],
    columns: [],
    total: 1001,
    source_rows: 1001,
    page: 0,
    size: 1000,
  };
  const studio = new Studio(
    fakeBackend([], {
      distill: () =>
        Promise.resolve({ generation: 1, leaf_summary: [], disagreements: [] }),
      tablePage: ({ page: index }) =>
        index === 0 ? Promise.resolve(page) : last.promise,
    }).backend,
  );
  const requested = studio.showRule();
  await settled();
  expect(studio.rule).toBeNull();
  last.resolve({ ...page, page: 1, rows: [{ x: 1.01 }], row_ids: [1000] });
  await requested;
  expect(studio.ruleDecimals.get('x')).toBe(2);
  expect(studio.rule?.generation).toBe(1);
});
