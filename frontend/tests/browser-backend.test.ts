import { afterEach, expect, test, vi } from 'vitest';
import { createBrowserBackend } from '../src/backend/browser';
import { BackendError } from '../src/backend/http';
import { runtimeLoading } from '../src/browser/loading.svelte';
import type { WorkspaceState } from '../src/backend/types';

const initial: WorkspaceState = {
  loaded: true,
  file_name: 'table.csv',
  notice: null,
  target: 'species',
  classes: ['a', 'b'],
  human: { '0': 'a' },
  eval_count: 0,
  threshold: 0.6,
  excluded_columns: [],
  generation: 1,
  refit_generation: null,
  proposals: {},
  confidence: {},
  abstained: [],
  missing: { a: 1, b: 2 },
  next_row: 1,
  evaluation: null,
  failure: null,
  dev_states: false,
};
const workers: WorkerStub[] = [];
class WorkerStub {
  onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  messages: Record<string, unknown>[] = [];
  terminate = vi.fn();
  constructor() {
    workers.push(this);
  }
  postMessage(message: Record<string, unknown>) {
    this.messages.push(message);
  }
  receive(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data }));
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  workers.length = 0;
  runtimeLoading.ready = false;
});

function setup() {
  runtimeLoading.ready = false;
  vi.stubGlobal('Worker', WorkerStub);
  vi.stubGlobal('location', { href: 'http://localhost/' });
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn() });
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          state: initial,
          session: {
            source: { sha256: 'a'.repeat(64) },
            target: 'species',
            human: initial.human,
            eval: {},
          },
          table: {
            rows: [{ x: 1 }, { x: 2 }],
            row_ids: [0, 1],
            columns: [],
            total: 2,
            source_rows: 2,
            page: 0,
            size: 100,
          },
        }),
      ),
    ),
  );
  const backend = createBrowserBackend();
  const worker = workers[0];
  if (worker === undefined) throw new Error('Worker was not created');
  return { backend, worker };
}

test('keeps the validated snapshot until a queued target is accepted', async () => {
  const { backend, worker } = setup();
  await backend.state();
  const rejected = backend.setTarget({
    target: 'invalid',
    classes: ['a', 'b'],
  });
  expect(await backend.state()).toEqual(initial);
  worker.receive({ kind: 'ready' });
  await vi.waitFor(() => {
    expect(worker.messages.some((m) => 'id' in m)).toBe(true);
  });
  const command = worker.messages.find((m) => 'id' in m);
  const failure = {
    error: 'Invalid target.',
    next_step: 'Choose another target.',
  };
  const assertion = expect(rejected).rejects.toMatchObject({ body: failure });
  worker.receive({
    kind: 'result',
    id: command?.id,
    value: JSON.stringify({ ok: false, error: failure }),
  });
  await assertion;
  expect(await backend.state()).toEqual(initial);
});

test('offers saved-label recovery on fatal runtime failure without promising Save session', async () => {
  const { backend, worker } = setup();
  await backend.state();
  worker.receive({ kind: 'fatal', error: 'Runtime stopped.' });
  const snapshot = await backend.state();
  expect(snapshot.human).toEqual(initial.human);
  expect(snapshot.failure?.next_step).toContain('Restore labels');
  expect(snapshot.failure?.next_step).not.toContain('Save session');
  await expect(backend.health()).rejects.toBeInstanceOf(BackendError);
});

test('keeps an accepted edit when a later queued mutation is rejected', async () => {
  const { backend, worker } = setup();
  await backend.state();
  worker.receive({ kind: 'ready' });
  const edit = backend.setLabel(1, { label: 'a' });
  const target = backend.setTarget({ target: 'invalid', classes: ['a', 'b'] });
  await vi.waitFor(() => {
    expect(worker.messages.filter((m) => 'id' in m)).toHaveLength(2);
  });
  const commands = worker.messages.filter((m) => 'id' in m);
  const accepted = { ...initial, generation: 2, human: { '0': 'a', '1': 'a' } };
  worker.receive({
    kind: 'result',
    id: commands[0]?.id,
    value: JSON.stringify({ ok: true, value: accepted }),
  });
  await edit;
  expect(await backend.state()).toEqual(accepted);
  const failure = {
    error: 'Invalid target.',
    next_step: 'Choose another target.',
  };
  const assertion = expect(target).rejects.toMatchObject({ body: failure });
  worker.receive({
    kind: 'result',
    id: commands[1]?.id,
    value: JSON.stringify({ ok: false, error: failure }),
  });
  await assertion;
  expect(await backend.state()).toEqual(accepted);
});

test('shows early labels immediately, retains later edits during replay and saves on failure', async () => {
  const { backend, worker } = setup();
  const saved = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value),
  });
  await backend.state();
  await expect(backend.setLabel(0, { label: 'b' })).resolves.toMatchObject({
    human: { '0': 'b' },
  });
  await backend.setLabel(0, { label: 'a' });
  await backend.setLabel(1, { label: 'b' });
  expect(worker.messages.filter((m) => 'id' in m)).toHaveLength(0);
  worker.receive({ kind: 'ready' });
  await vi.waitFor(() => {
    expect(worker.messages.filter((m) => 'id' in m)).toHaveLength(3);
  });
  const commands = worker.messages.filter((m) => 'id' in m);
  worker.receive({
    kind: 'result',
    id: commands[0]?.id,
    value: JSON.stringify({
      ok: true,
      value: { ...initial, generation: 2, human: { '0': 'b' } },
    }),
  });
  await vi.waitFor(async () => {
    expect((await backend.state()).human).toEqual({ '0': 'a', '1': 'b' });
  });
  worker.receive({ kind: 'fatal', error: 'Runtime stopped.' });
  expect((await backend.state()).human).toEqual({ '0': 'a', '1': 'b' });
  expect(saved.size).toBe(1);
  expect(JSON.parse([...saved.values()][0] ?? '{}')).toMatchObject({
    human: { '0': 'a', '1': 'b' },
  });
});
