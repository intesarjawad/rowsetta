import * as decode from './decode';
import type { LabelRecovery } from '../browser/labels.svelte';
import type {
  DemoInput,
  Distilled,
  DistillInput,
  ErrorBody,
  ExclusionInput,
  ExportArtifact,
  ExportQuery,
  LabelInput,
  LeakHint,
  Suspect,
  ServerEvent,
  TablePage,
  TableQuery,
  TargetInput,
  ThresholdInput,
  WorkspaceState,
} from './types';

export type Fetch = (input: string, init: RequestInit) => Promise<Response>;

/**
 * Why a request failed: the server refused it with its error contract, no server
 * answered, or the answer did not have the shape these types declare.
 */
export type FailureKind = 'rejected' | 'unreachable' | 'malformed';

/** Every failure carries an `ErrorBody`, so the interface renders all three the same way. */
export class BackendError extends Error {
  constructor(
    readonly kind: FailureKind,
    readonly body: ErrorBody,
    /** `null` when no response arrived. */
    readonly status: number | null,
    options?: ErrorOptions,
  ) {
    super(body.error, options);
    this.name = 'BackendError';
  }
}

const UNREACHABLE: ErrorBody = {
  error: 'The local server did not respond.',
  next_step:
    'Check that rowsetta is still running in your terminal, then reload this page.',
};

// The likeliest cause is a page left open across an upgrade, served by a newer server.
const MALFORMED_NEXT_STEP =
  'Reload this page; if it repeats, reinstall rowsetta.';

// A restarted local server is back within seconds; the cap keeps a stopped one
// from being asked more than twice a minute.
const RECONNECT_FIRST_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

/** The part of `EventSource` the client uses. */
export interface EventChannel {
  addEventListener(
    type: string,
    listener: (event: MessageEvent<unknown>) => void,
  ): void;
  close(): void;
}

export type OpenEvents = (url: string) => EventChannel;

export interface Backend {
  readonly recovery?: LabelRecovery;
  restoreLabels?(session: string): Promise<WorkspaceState>;
  state(): Promise<WorkspaceState>;
  loadDemo(): Promise<WorkspaceState>;
  uploadCsv(file: File): Promise<WorkspaceState>;
  tablePage(query: TableQuery): Promise<TablePage>;
  setTarget(input: TargetInput): Promise<WorkspaceState>;
  setLabel(rowId: number, input: LabelInput): Promise<WorkspaceState>;
  undo(): Promise<WorkspaceState>;
  /** The next blind evaluation row, or `null` when every row has been served. */
  nextEvalRow(): Promise<number | null>;
  setExcluded(column: string, input: ExclusionInput): Promise<WorkspaceState>;
  setThreshold(input: ThresholdInput): Promise<WorkspaceState>;
  distill(input: DistillInput): Promise<Distilled>;
  /** Columns that may leak the answer; empty until enough human labels exist. */
  audit(): Promise<LeakHint[]>;
  /** Human labels from least to most plausible, each scored out of fold. */
  suspects(): Promise<Suspect[]>;
  /** The current rule, after the server has checked its SQL against every source row. */
  exportRule(query: ExportQuery): Promise<ExportArtifact>;
  /** Whether the server answers; the one route that needs no launch session. */
  health(): Promise<boolean>;
  /** The session file: target, classes, labels and settings, as saved on disk. */
  session(): Promise<Blob>;
  /**
   * Follow refit events, reconnecting with a doubling wait after each drop.
   * Returns a function that stops following.
   */
  events(listener: (event: ServerEvent) => void): () => void;
}

function malformedBody(cause: Error): ErrorBody {
  return {
    error: `The local server sent an unexpected response (${cause.message}).`,
    next_step: MALFORMED_NEXT_STEP,
  };
}

function malformed(status: number, cause: Error): BackendError {
  return new BackendError('malformed', malformedBody(cause), status, {
    cause,
  });
}

function isDecodingFailure(
  error: unknown,
): error is decode.DecodeError | SyntaxError {
  return error instanceof decode.DecodeError || error instanceof SyntaxError;
}

async function rejection(response: Response): Promise<BackendError> {
  try {
    const body = decode.errorBody(await response.json(), 'error');
    return new BackendError('rejected', body, response.status);
  } catch (error) {
    if (!isDecodingFailure(error)) throw error;
    return malformed(response.status, error);
  }
}

async function decoded<T>(
  response: Response,
  decodeBody: (value: unknown, path: string) => T,
  path: string,
): Promise<T> {
  try {
    return decodeBody(await response.json(), path);
  } catch (error) {
    if (!isDecodingFailure(error)) throw error;
    throw malformed(response.status, error);
  }
}

function json(method: 'POST' | 'PUT', body: object): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

function relay(
  channel: EventChannel,
  name: string,
  toEvent: (data: unknown, path: string) => ServerEvent,
  listener: (event: ServerEvent) => void,
): void {
  channel.addEventListener(name, ({ data }) => {
    let event: ServerEvent;
    try {
      event = toEvent(typeof data === 'string' ? JSON.parse(data) : data, name);
    } catch (error) {
      if (!isDecodingFailure(error)) throw error;
      event = { kind: 'malformed', failure: malformedBody(error) };
    }
    listener(event);
  });
}

function follow(
  openEvents: OpenEvents,
  listener: (event: ServerEvent) => void,
): () => void {
  let retryMs = RECONNECT_FIRST_MS;
  let reconnect: ReturnType<typeof setTimeout> | undefined;

  function connect(): EventChannel {
    const channel = openEvents('/events');
    channel.addEventListener('open', () => {
      retryMs = RECONNECT_FIRST_MS;
      listener({ kind: 'connected' });
    });
    // EventSource retries a dropped connection at its own pace but gives up
    // after an HTTP error; closing and reopening handles both the same way.
    channel.addEventListener('error', () => {
      channel.close();
      listener({ kind: 'disconnected', retryMs });
      reconnect = setTimeout(() => {
        current = connect();
      }, retryMs);
      retryMs = Math.min(retryMs * 2, RECONNECT_MAX_MS);
    });
    relay(
      channel,
      'refit_started',
      (data, path) => ({
        kind: 'refit_started',
        generation: decode.generation(data, path),
      }),
      listener,
    );
    relay(
      channel,
      'progress',
      (data, path) => ({ kind: 'progress', ...decode.progress(data, path) }),
      listener,
    );
    relay(
      channel,
      'refit_done',
      (data, path) => ({
        kind: 'refit_done',
        generation: decode.generation(data, path),
      }),
      listener,
    );
    relay(
      channel,
      'refit_failed',
      (data, path) => ({
        kind: 'refit_failed',
        failure: decode.errorBody(data, path),
      }),
      listener,
    );
    return channel;
  }

  let current = connect();
  return () => {
    clearTimeout(reconnect);
    current.close();
  };
}

/** Same-origin client; the launch cookie authenticates each request and the event stream. */
export function createBackend(
  fetchResource: Fetch = (input, init) => fetch(input, init),
  openEvents: OpenEvents = (url) => new EventSource(url),
): Backend {
  async function send(input: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await fetchResource(input, init);
    } catch (cause) {
      throw new BackendError('unreachable', UNREACHABLE, null, { cause });
    }
    if (!response.ok) throw await rejection(response);
    return response;
  }

  async function workspace(
    input: string,
    init: RequestInit,
  ): Promise<WorkspaceState> {
    return decoded(await send(input, init), decode.workspaceState, 'state');
  }

  const get: RequestInit = { method: 'GET' };
  const demo: DemoInput = { demo: 'penguins' };

  return {
    state: () => workspace('/state', get),
    loadDemo: () => workspace('/table', json('POST', demo)),
    uploadCsv: (file) => {
      const form = new FormData();
      form.append('file', file, file.name);
      return workspace('/table', { method: 'POST', body: form });
    },
    tablePage: async ({ page, size }) => {
      const query = new URLSearchParams({
        page: String(page),
        size: String(size),
      });
      return decoded(
        await send(`/table?${query.toString()}`, get),
        decode.tablePage,
        'table',
      );
    },
    setTarget: (input) => workspace('/target', json('POST', input)),
    setLabel: (rowId, input) =>
      workspace(`/labels/${String(rowId)}`, json('PUT', input)),
    undo: () => workspace('/undo', { method: 'POST' }),
    nextEvalRow: async () =>
      decoded(await send('/eval/next', get), decode.nextEvalRow, 'eval'),
    setExcluded: (column, input) =>
      workspace(
        `/columns/${encodeURIComponent(column)}/excluded`,
        json('PUT', input),
      ),
    setThreshold: (input) => workspace('/threshold', json('PUT', input)),
    distill: async (input) =>
      decoded(
        await send('/distill', json('POST', input)),
        decode.distilled,
        'distill',
      ),
    audit: async () =>
      decoded(await send('/audit', get), decode.leaks, 'audit'),
    suspects: async () =>
      decoded(await send('/suspects', get), decode.suspects, 'suspects'),
    exportRule: async ({ format, dialect }) => {
      const query = new URLSearchParams({ format, dialect });
      const response = await send(`/export?${query.toString()}`, get);
      if (format === 'dbt') {
        return {
          format,
          files: await decoded(response, decode.dbtFiles, 'export'),
        };
      }
      return { format, text: await response.text() };
    },
    health: async () =>
      decoded(await send('/health', get), decode.health, 'health'),
    session: async () => (await send('/session', get)).blob(),
    events: (listener) => follow(openEvents, listener),
  };
}
