import type { Backend } from './http';
import { BackendError } from './http';
import * as decode from './decode';
import type {
  ErrorBody,
  ServerEvent,
  WorkspaceState,
  TablePage,
  LabelInput,
} from './types';
import { LabelRecovery } from '../browser/labels.svelte';
import { BROWSER_ASSETS } from '../browser/config';
import { runtimeLoading, teacherName } from '../browser/loading.svelte';

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function object(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new Error('Invalid worker response');
  return value;
}

/** Tab-local worker backend; the only network calls load static application assets. */
export function createBrowserBackend(): Backend {
  const worker = new Worker(
    new URL('../browser/pyodide.worker.ts', import.meta.url),
    { type: 'module' },
  );
  const recovery = new LabelRecovery();
  const pending = new Map<
    number,
    { resolve: (value: unknown) => void; reject: (error: Error) => void }
  >();
  const listeners = new Set<(event: ServerEvent) => void>();
  const emit = (event: ServerEvent) => {
    for (const listener of listeners) listener(event);
  };
  let sequence = 0;
  let snapshot: WorkspaceState;
  let firstPage: TablePage;
  let demoSession: Record<string, unknown>;
  const queuedLabels = new Set<LabelInput & { action: 'label'; row: number }>();
  let runtimeFailure: ErrorBody | null = null;
  let readyResolve: () => void = () => {};
  let readyReject: (error: Error) => void = () => {};
  const ready = new Promise<void>((resolve, reject) => {
    readyResolve = resolve;
    readyReject = reject;
  });
  const initial = fetch(`${BROWSER_ASSETS}demo.json`).then(async (response) => {
    if (!response.ok) throw new Error('The bundled demo could not be loaded.');
    const body = object(await response.json());
    snapshot = browserState(body.state);
    firstPage = decode.tablePage(body.table, 'demo.table');
    demoSession = object(body.session);
    recovery.offer(JSON.stringify(demoSession));
  });

  function failed(message: string): BackendError {
    return new BackendError(
      'rejected',
      {
        error: message,
        next_step:
          'Reload this page, reopen the same CSV and target, then choose Restore labels to recover saved labels.',
      },
      null,
    );
  }

  function fatal(message: string): void {
    worker.terminate();
    const error = failed(message);
    runtimeFailure = error.body;
    readyReject(error);
    for (const request of pending.values()) request.reject(error);
    pending.clear();
    emit({ kind: 'malformed', failure: error.body });
  }

  worker.onmessage = (event: MessageEvent<unknown>) => {
    const data = object(event.data);
    if (
      data.kind === 'loading' &&
      typeof data.done === 'number' &&
      typeof data.total === 'number'
    ) {
      runtimeLoading.done = data.done;
      runtimeLoading.total = data.total;
    } else if (data.kind === 'teacher' && typeof data.fullModel === 'boolean') {
      runtimeLoading.fullModel = data.fullModel;
      runtimeLoading.model = teacherName(data.fullModel);
    } else if (
      data.kind === 'model-loading' &&
      isObject(data.progress) &&
      typeof data.progress.loaded === 'number' &&
      typeof data.progress.total === 'number'
    ) {
      runtimeLoading.modelDone = data.progress.loaded;
      runtimeLoading.modelTotal = data.progress.total;
    } else if (data.kind === 'labels' && typeof data.session === 'string') {
      if (queuedLabels.size === 0) {
        if (data.save === true) recovery.save(data.session);
        else recovery.offer(data.session);
      }
    } else if (data.kind === 'table-loaded') {
      recovery.pending = null;
    } else if (data.kind === 'ready') {
      runtimeLoading.ready = true;
      readyResolve();
    } else if (data.kind === 'fatal' && typeof data.error === 'string') {
      fatal(data.error);
    } else if (
      data.kind === 'result' &&
      typeof data.id === 'number' &&
      typeof data.value === 'string'
    ) {
      const request = pending.get(data.id);
      pending.delete(data.id);
      if (request === undefined) return;
      const result = object(JSON.parse(data.value));
      if (result.ok === true) request.resolve(result.value);
      else
        request.reject(
          new BackendError(
            'rejected',
            decode.errorBody(result.error, 'worker.error'),
            null,
          ),
        );
    }
  };
  worker.onerror = (event) => {
    fatal(event.message);
  };
  worker.postMessage({
    base: new URL(BROWSER_ASSETS, location.href).href,
    today: new Date().toISOString().slice(0, 10),
  });
  // Retain failures even when the visitor has not issued a command yet.
  void ready.catch(() => {});

  async function call(message: Record<string, unknown>): Promise<unknown> {
    const id = ++sequence;
    await ready;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      worker.postMessage({ id, message: JSON.stringify(message) });
    });
  }

  function browserState(value: unknown): WorkspaceState {
    const state = decode.workspaceState(value, 'state');
    return {
      ...state,
      notice:
        state.notice?.startsWith('Browser labels') === true
          ? null
          : state.notice,
    };
  }

  async function mutate(
    message: Record<string, unknown>,
  ): Promise<WorkspaceState> {
    await initial;
    const state = browserState(await call(message));
    if (state.generation >= snapshot.generation) {
      runtimeFailure = null;
      snapshot = state;
      emit({ kind: 'refit_done', generation: state.generation });
    }
    return labelledState();
  }

  function labelledState(): WorkspaceState {
    const human = new Map(Object.entries(snapshot.human));
    for (const { row, label } of queuedLabels) {
      if (label === null) human.delete(String(row));
      else human.set(String(row), label);
    }
    return {
      ...snapshot,
      human: Object.fromEntries(human),
      failure: runtimeFailure,
    };
  }

  return {
    recovery,
    restoreLabels: async (session) => {
      const offered = recovery.pending;
      const state = await mutate({ action: 'restore', session });
      if (recovery.pending === offered) recovery.pending = null;
      return state;
    },
    state: async () => {
      await initial;
      return labelledState();
    },
    loadDemo: async () =>
      mutate({
        action: 'load',
        csv: await (await fetch(`${BROWSER_ASSETS}penguins.csv`)).text(),
        file_name: 'penguins.csv',
      }),
    uploadCsv: async (file) => {
      if (file.size > 50_000_000)
        throw failed(
          'This CSV exceeds the 50 MB browser limit. Open it in the local app.',
        );
      let csv: string;
      try {
        csv = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(
          await file.arrayBuffer(),
        );
      } catch {
        throw failed(
          'This CSV is not UTF-8. Save a UTF-8 CSV and open that file.',
        );
      }
      return mutate({
        action: 'load',
        csv,
        file_name: file.name,
      });
    },
    tablePage: async (query) => {
      await initial;
      if (!runtimeLoading.ready)
        return {
          ...firstPage,
          page: query.page,
          size: query.size,
          row_ids: firstPage.row_ids.slice(
            query.page * query.size,
            (query.page + 1) * query.size,
          ),
          rows: firstPage.rows.slice(
            query.page * query.size,
            (query.page + 1) * query.size,
          ),
        };
      return decode.tablePage(
        await call({ action: 'table', ...query }),
        'table',
      );
    },
    setTarget: (input) =>
      mutate({ action: 'target', ...input, classes: input.classes ?? [] }),
    setLabel: async (row, input) => {
      if (runtimeLoading.ready)
        return mutate({ action: 'label', row, ...input });
      await initial;
      if (
        input.mode === 'eval' ||
        !firstPage.row_ids.includes(row) ||
        (input.label !== null && !snapshot.classes.includes(input.label))
      )
        throw failed('Choose a row and class from the demo table.');
      const message = { action: 'label', row, ...input } as const;
      queuedLabels.add(message);
      const state = labelledState();
      recovery.save(JSON.stringify({ ...demoSession, human: state.human }));
      void call(message)
        .then((value) => {
          const accepted = browserState(value);
          queuedLabels.delete(message);
          if (accepted.generation >= snapshot.generation) snapshot = accepted;
          emit({ kind: 'refit_done', generation: snapshot.generation });
        })
        .catch((error: unknown) => {
          emit({
            kind: 'malformed',
            failure:
              error instanceof BackendError
                ? error.body
                : failed(String(error)).body,
          });
        });
      return state;
    },
    undo: () => mutate({ action: 'undo' }),
    nextEvalRow: async () =>
      decode.nextEvalRow(await call({ action: 'eval' }), 'eval'),
    setExcluded: (column, input) =>
      mutate({ action: 'exclude', column, ...input }),
    setThreshold: (input) => mutate({ action: 'threshold', ...input }),
    distill: async (input) =>
      decode.distilled(await call({ action: 'distill', ...input }), 'distill'),
    audit: async () => decode.leaks(await call({ action: 'audit' }), 'audit'),
    suspects: () =>
      Promise.reject(failed('Label audit is available in the local app.')),
    exportRule: async (query) => {
      const value = await call({ action: 'export', ...query });
      if (query.format === 'dbt')
        return { format: 'dbt', files: decode.dbtFiles(value, 'export') };
      if (typeof value !== 'string') throw failed('Invalid export response');
      return { format: query.format, text: value };
    },
    health: async () => {
      await ready;
      return true;
    },
    session: async () => {
      const value = await call({ action: 'session' });
      if (typeof value !== 'string') throw failed('Invalid session response');
      return new Blob([value], { type: 'application/json' });
    },
    events: (listener) => {
      listeners.add(listener);
      void initial
        .then(() => {
          listener({ kind: 'connected' });
        })
        .catch((error: unknown) => {
          fatal(String(error));
        });
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) worker.terminate();
      };
    },
  };
}
