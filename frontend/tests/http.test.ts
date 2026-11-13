import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BackendError, createBackend, type Fetch } from '../src/backend/http';
import type {
  ServerEvent,
  TablePage,
  WorkspaceState,
} from '../src/backend/types';

const STATE: WorkspaceState = {
  file_name: 'penguins.csv',
  loaded: true,
  notice: null,
  target: 'species',
  classes: ['Adelie', 'Chinstrap', 'Gentoo'],
  human: { '0': 'Adelie', '152': 'Chinstrap' },
  eval_count: 20,
  threshold: 0.6,
  excluded_columns: ['island'],
  generation: 4,
  refit_generation: 3,
  proposals: { '1': 'Adelie' },
  confidence: { '1': 0.93 },
  abstained: [7, 9],
  missing: { Gentoo: 2 },
  next_row: 11,
  evaluation: {
    n: 20,
    accuracy: { kind: 'measured', value: 0.9, lo: 0.7, hi: 0.97 },
    balanced_accuracy: { kind: 'needs_rows', counts: { Adelie: 9, Gentoo: 4 } },
    per_class_recall: { Adelie: 1, Chinstrap: null, Gentoo: 0.75 },
    majority_class: 'Adelie',
    majority_baseline: 0.45,
  },
  failure: null,
  dev_states: false,
};

const PAGE: TablePage = {
  rows: [
    { species: null, bill_length_mm: 39.1, island: 'Torgersen', ok: true },
  ],
  row_ids: [0],
  columns: [
    {
      name: 'bill_length_mm',
      kind: 'numeric',
      distinct_ratio: 0.48,
      missing_ratio: 0.01,
    },
  ],
  total: 344,
  source_rows: 344,
  page: 0,
  size: 1,
};

interface Sent {
  input: string;
  init: RequestInit;
}

function serving(response: () => Response): { fetch: Fetch; sent: Sent[] } {
  const sent: Sent[] = [];
  return {
    sent,
    fetch: (input, init) => {
      sent.push({ input, init });
      return Promise.resolve(response());
    },
  };
}

async function failure(call: Promise<unknown>): Promise<BackendError> {
  const error: unknown = await call.then(
    () => undefined,
    (reason: unknown) => reason,
  );
  if (!(error instanceof BackendError)) {
    throw new Error(`expected a BackendError, got ${String(error)}`);
  }
  return error;
}

describe('successful responses', () => {
  it('returns the decoded workspace state', async () => {
    const { fetch, sent } = serving(() => Response.json(STATE));

    expect(await createBackend(fetch).state()).toEqual(STATE);
    expect(sent).toEqual([{ input: '/state', init: { method: 'GET' } }]);
  });

  it('accepts a state with no table loaded', async () => {
    const empty: WorkspaceState = {
      ...STATE,
      loaded: false,
      file_name: null,
      target: null,
      classes: [],
      human: {},
      eval_count: 0,
      threshold: 0,
      excluded_columns: [],
      generation: 0,
      refit_generation: null,
      proposals: {},
      confidence: {},
      abstained: [],
      missing: {},
      next_row: null,
      evaluation: null,
    };
    const { fetch } = serving(() => Response.json(empty));

    expect(await createBackend(fetch).state()).toEqual(empty);
  });

  it('carries a refit failure inside the state rather than rejecting', async () => {
    const failed = {
      ...STATE,
      failure: { error: 'Refit failed.', next_step: 'rowsetta doctor' },
    };
    const { fetch } = serving(() => Response.json(failed));

    expect((await createBackend(fetch).state()).failure).toEqual(
      failed.failure,
    );
  });

  it('pages the table with explicit query parameters', async () => {
    const { fetch, sent } = serving(() => Response.json(PAGE));

    expect(
      await createBackend(fetch).tablePage({ page: 3, size: 100 }),
    ).toEqual(PAGE);
    expect(sent[0]?.input).toBe('/table?page=3&size=100');
  });

  it('sends a label as JSON to the row it names', async () => {
    const { fetch, sent } = serving(() => Response.json(STATE));

    await createBackend(fetch).setLabel(152, { label: null });

    expect(sent).toEqual([
      {
        input: '/labels/152',
        init: {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: '{"label":null}',
        },
      },
    ]);
  });

  it('escapes column names used as path segments', async () => {
    const { fetch, sent } = serving(() => Response.json(STATE));

    await createBackend(fetch).setExcluded('size/weight (g)', {
      excluded: true,
    });

    expect(sent[0]?.input).toBe('/columns/size%2Fweight%20(g)/excluded');
  });

  it('uploads one CSV file as multipart form data', async () => {
    const { fetch, sent } = serving(() => Response.json(STATE));
    const file = new File(['bill_length_mm\n39.1\n'], 'penguins.csv', {
      type: 'text/csv',
    });

    await createBackend(fetch).uploadCsv(file);

    const body = sent[0]?.init.body;
    expect(body).toBeInstanceOf(FormData);
    expect(body instanceof FormData ? [...body.values()] : []).toEqual([file]);
  });

  it('returns the next evaluation row, or null once none remain', async () => {
    const next = serving(() => Response.json({ row_id: 41 }));
    const done = serving(() => Response.json({ row_id: null }));

    expect(await createBackend(next.fetch).nextEvalRow()).toBe(41);
    expect(await createBackend(done.fetch).nextEvalRow()).toBeNull();
  });

  it('decodes distilled leaf lines and leak hints', async () => {
    const line = {
      line_no: 1,
      conditions: [['flipper_length_mm', '<=', '206.5']],
      label: 'Adelie',
      row_ids: [0, 1],
      agree: { k: 2, n: 2, coverage: { answered: 2, total: 2 } },
    };
    const leak = {
      column: 'id',
      kind: 'identifier',
      reason: 'Unique per row.',
      score: null,
    };
    const distilled = serving(() =>
      Response.json({
        leaf_summary: [line],
        disagreements: [1],
        generation: 4,
      }),
    );
    const audited = serving(() => Response.json({ leaks: [leak] }));
    const suspect = {
      row_id: 3,
      given: 'Gentoo',
      given_probability: 0.02,
      likely: 'Adelie',
    };
    const checked = serving(() => Response.json({ suspects: [suspect] }));

    expect(
      await createBackend(distilled.fetch).distill({ max_depth: 2 }),
    ).toEqual({
      leaf_summary: [line],
      disagreements: [1],
      generation: 4,
    });
    expect(await createBackend(audited.fetch).audit()).toEqual([leak]);
    expect(await createBackend(checked.fetch).suspects()).toEqual([suspect]);
  });

  it('returns SQL as text and a dbt project as files', async () => {
    const sql = serving(() => new Response('select 1;\n', { status: 200 }));
    const dbt = serving(() =>
      Response.json({ 'models/rule.sql': 'select 1;\n' }),
    );

    expect(
      await createBackend(sql.fetch).exportRule({
        format: 'sql',
        dialect: 'sqlite',
      }),
    ).toEqual({ format: 'sql', text: 'select 1;\n' });
    expect(sql.sent[0]?.input).toBe('/export?format=sql&dialect=sqlite');
    expect(
      await createBackend(dbt.fetch).exportRule({
        format: 'dbt',
        dialect: 'duckdb',
      }),
    ).toEqual({ format: 'dbt', files: { 'models/rule.sql': 'select 1;\n' } });
  });
});

describe('health and session download', () => {
  it('reports a server that answers its health probe', async () => {
    const { fetch, sent } = serving(() => Response.json({ ok: true }));

    expect(await createBackend(fetch).health()).toBe(true);
    expect(sent).toEqual([{ input: '/health', init: { method: 'GET' } }]);
  });

  it('treats a health answer without `ok` as malformed', async () => {
    const { fetch } = serving(() => Response.json({ status: 'up' }));

    const error = await failure(createBackend(fetch).health());

    expect(error.kind).toBe('malformed');
    expect(error.body.error).toContain('health.ok');
  });

  it('returns the session file as it was served', async () => {
    const saved = '{"target": "species", "human": {"0": "Adelie"}}';
    const { fetch, sent } = serving(
      () =>
        new Response(saved, {
          headers: { 'Content-Type': 'application/json' },
        }),
    );

    const file = await createBackend(fetch).session();

    expect(sent).toEqual([{ input: '/session', init: { method: 'GET' } }]);
    expect(file.type).toBe('application/json');
    expect(await file.text()).toBe(saved);
  });

  it('rejects a session download before any target is chosen', async () => {
    const body = {
      error: 'Choose a target and its classes first.',
      next_step: 'rowsetta demo; load a CSV and choose its target.',
    };
    const { fetch } = serving(() => Response.json(body, { status: 409 }));

    const error = await failure(createBackend(fetch).session());

    expect(error.kind).toBe('rejected');
    expect(error.body).toEqual(body);
  });
});

type Listener = (event: MessageEvent<unknown>) => void;

class FakeChannel {
  readonly url: string;
  closed = false;
  private readonly listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.closed = true;
  }

  dispatch(type: string, data?: unknown): void {
    const event = new MessageEvent(type, {
      data: data === undefined ? undefined : JSON.stringify(data),
    });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function following(): {
  channels: FakeChannel[];
  received: ServerEvent[];
  stop: () => void;
} {
  const channels: FakeChannel[] = [];
  const received: ServerEvent[] = [];
  const backend = createBackend(
    () => Promise.reject(new Error('no fetch expected')),
    (url) => {
      const channel = new FakeChannel(url);
      channels.push(channel);
      return channel;
    },
  );
  const stop = backend.events((event) => {
    received.push(event);
  });
  return { channels, received, stop };
}

function latest(channels: readonly FakeChannel[]): FakeChannel {
  const channel = channels.at(-1);
  if (channel === undefined) throw new Error('no event stream was opened');
  return channel;
}

describe('server events', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('decodes each refit event from the stream', () => {
    const { channels, received } = following();
    const channel = latest(channels);

    channel.dispatch('open');
    channel.dispatch('refit_started', { generation: 4 });
    channel.dispatch('progress', { done: 120, total: 338 });
    channel.dispatch('refit_done', { generation: 4 });
    channel.dispatch('refit_failed', {
      error: 'The model file is missing or failed its checksum.',
      next_step: 'rowsetta doctor --fix',
    });

    expect(channel.url).toBe('/events');
    expect(received).toEqual([
      { kind: 'connected' },
      { kind: 'refit_started', generation: 4 },
      { kind: 'progress', done: 120, total: 338 },
      { kind: 'refit_done', generation: 4 },
      {
        kind: 'refit_failed',
        failure: {
          error: 'The model file is missing or failed its checksum.',
          next_step: 'rowsetta doctor --fix',
        },
      },
    ]);
  });

  it('reports an event that breaks the contract as malformed', () => {
    const { channels, received } = following();

    latest(channels).dispatch('progress', { done: '120', total: 338 });

    expect(received).toHaveLength(1);
    const [event] = received;
    expect(event?.kind).toBe('malformed');
    expect(event?.kind === 'malformed' && event.failure.error).toContain(
      'progress.done',
    );
  });

  it('reconnects after a drop, doubling the wait up to a cap', () => {
    const { channels, received } = following();
    const waits: number[] = [];

    for (let drop = 0; drop < 7; drop += 1) {
      const channel = latest(channels);
      channel.dispatch('error');
      expect(channel.closed).toBe(true);
      const last = received.at(-1);
      if (last?.kind !== 'disconnected') throw new Error('expected a drop');
      waits.push(last.retryMs);
      vi.advanceTimersByTime(last.retryMs - 1);
      expect(channels).toHaveLength(drop + 1);
      vi.advanceTimersByTime(1);
      expect(channels).toHaveLength(drop + 2);
    }

    expect(waits).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);
  });

  it('starts the wait over once a reconnection opens', () => {
    const { channels, received } = following();

    latest(channels).dispatch('error');
    vi.runOnlyPendingTimers();
    latest(channels).dispatch('error');
    vi.runOnlyPendingTimers();
    latest(channels).dispatch('open');
    latest(channels).dispatch('error');

    expect(received).toEqual([
      { kind: 'disconnected', retryMs: 1000 },
      { kind: 'disconnected', retryMs: 2000 },
      { kind: 'connected' },
      { kind: 'disconnected', retryMs: 1000 },
    ]);
  });

  it('stops following: closes the stream and cancels a pending reconnect', () => {
    const open = following();
    open.stop();
    expect(latest(open.channels).closed).toBe(true);

    const dropped = following();
    latest(dropped.channels).dispatch('error');
    dropped.stop();
    vi.runAllTimers();

    expect(dropped.channels).toHaveLength(1);
  });
});

describe('failures', () => {
  it('surfaces the backend error contract, including missing labels', async () => {
    const body = {
      error: 'Proposals start once every class has 2 labels.',
      next_step: 'rowsetta demo; label 2 more rows of: Gentoo',
      missing: { Gentoo: 2 },
    };
    const { fetch } = serving(() => Response.json(body, { status: 409 }));

    const error = await failure(createBackend(fetch).undo());

    expect(error.kind).toBe('rejected');
    expect(error.status).toBe(409);
    expect(error.body).toEqual(body);
    expect(error.message).toBe(body.error);
  });

  it('reports an error response outside the contract as malformed', async () => {
    const { fetch } = serving(
      () => new Response('<html>Bad Gateway</html>', { status: 502 }),
    );

    const error = await failure(createBackend(fetch).state());

    expect(error.kind).toBe('malformed');
    expect(error.status).toBe(502);
    expect(error.body.next_step).not.toBe('');
  });

  it('names the offending field when a success response breaks the contract', async () => {
    const { fetch } = serving(() =>
      Response.json({ ...STATE, generation: '4' }),
    );

    const error = await failure(createBackend(fetch).state());

    expect(error.kind).toBe('malformed');
    expect(error.status).toBe(200);
    expect(error.body.error).toContain('state.generation');
  });

  it('rejects an evaluation with an unknown measurement kind', async () => {
    const evaluation = {
      ...STATE.evaluation,
      accuracy: { kind: 'guessed', value: 1 },
    };
    const { fetch } = serving(() => Response.json({ ...STATE, evaluation }));

    const error = await failure(createBackend(fetch).state());

    expect(error.body.error).toContain('state.evaluation.accuracy.kind');
  });

  it('reports a server that does not answer as unreachable', async () => {
    const cause = new TypeError('fetch failed');
    const backend = createBackend(() => Promise.reject(cause));

    const error = await failure(backend.state());

    expect(error.kind).toBe('unreachable');
    expect(error.status).toBeNull();
    expect(error.cause).toBe(cause);
  });
});
