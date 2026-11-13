// Wire types for the local HTTP API. Field names keep the backend's snake_case so
// a body reads the same in the browser, the server and the session file.
// Request and response bodies mirror src/rowsetta/api/schemas.py and are
// checked against tests/openapi.json. Server events are not in that schema; they
// mirror src/rowsetta/api/runtime.py. http.ts decodes every response.

export const LABEL_MODES = ['human', 'eval'] as const;
export type LabelMode = (typeof LABEL_MODES)[number];

export const EXPORT_FORMATS = ['sql', 'dbt', 'python', 'json'] as const;
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

export const SQL_DIALECTS = ['duckdb', 'postgres', 'sqlite'] as const;
export type SqlDialect = (typeof SQL_DIALECTS)[number];

export const COLUMN_KINDS = [
  'numeric',
  'categorical',
  'text',
  'datetime',
] as const;
export type ColumnKind = (typeof COLUMN_KINDS)[number];

export const LEAK_KINDS = ['identifier', 'single-column', 'name'] as const;
export type LeakKind = (typeof LEAK_KINDS)[number];

export interface DemoInput {
  demo: 'penguins';
}

export interface TargetInput {
  target: string;
  /** Omitted, the server takes the classes and human labels from the `target` column. */
  classes?: readonly string[];
}

export interface LabelInput {
  /** `null` clears the row's answer. */
  label: string | null;
  mode?: LabelMode;
}

export interface ExclusionInput {
  excluded: boolean;
}

export interface ThresholdInput {
  /** Minimum probability or leaf purity, from 0 to 1, required for an answer. */
  threshold: number;
}

export interface DistillInput {
  max_depth?: number;
}

export interface TableQuery {
  page: number;
  size: number;
}

export interface ExportQuery {
  format: ExportFormat;
  dialect: SqlDialect;
}

/** Every failed request, and a failed refit inside the state, carries this body. */
export interface ErrorBody {
  error: string;
  next_step: string;
  /** Human labels still needed per class before proposals can start. */
  missing?: Readonly<Record<string, number>>;
}

/** Row ids are JSON object keys, so maps keyed by row arrive with string keys. */
export type ByRow<T> = Readonly<Record<string, T>>;

export interface Measured {
  kind: 'measured';
  value: number;
  /** Lower and upper bounds of the 95% interval. */
  lo: number;
  hi: number;
}

/** A measurement withheld until each class has enough evaluation rows. */
export interface NeedsRows {
  kind: 'needs_rows';
  counts: Readonly<Record<string, number>>;
}

export interface Evaluation {
  n: number;
  accuracy: Measured;
  balanced_accuracy: Measured | NeedsRows;
  /** `null` for a class with no evaluation rows. */
  per_class_recall: Readonly<Record<string, number | null>>;
  majority_class: string;
  majority_baseline: number;
}

export interface WorkspaceState {
  loaded: boolean;
  file_name?: string | null;
  notice: string | null;
  target: string | null;
  classes: readonly string[];
  human: ByRow<string>;
  eval_count: number;
  threshold: number;
  excluded_columns: readonly string[];
  /** Increments on every input change; proposals are current when `refit_generation` equals it. */
  generation: number;
  refit_generation: number | null;
  proposals: ByRow<string>;
  confidence: ByRow<number>;
  abstained: readonly number[];
  missing: Readonly<Record<string, number>>;
  next_row: number | null;
  /** `null` until twenty evaluation rows are labelled. */
  evaluation: Evaluation | null;
  failure: ErrorBody | null;
  dev_states: boolean;
}

export type Cell = string | number | boolean | null;

export interface ColumnInfo {
  name: string;
  kind: ColumnKind;
  distinct_ratio: number;
  missing_ratio: number;
}

export interface TablePage {
  /** The target column is always `null` here; answers come from the state. */
  rows: readonly Readonly<Record<string, Cell>>[];
  row_ids: readonly number[];
  columns: readonly ColumnInfo[];
  total: number;
  source_rows: number;
  page: number;
  size: number;
}

/** A split test as `[column, operator, value]`, already rendered for display. */
export type Condition = readonly [string, string, string];

export interface LeafLine {
  line_no: number;
  conditions: readonly Condition[];
  /** `null` when the leaf abstains. */
  label: string | null;
  row_ids: readonly number[];
  agree: {
    k: number;
    n: number;
    coverage: { answered: number; total: number };
  };
}

export interface Distilled {
  leaf_summary: readonly LeafLine[];
  /** Rows where the rule and the model both answer, differently. */
  disagreements: readonly number[];
  generation: number;
}

export interface LeakHint {
  column: string;
  kind: LeakKind;
  reason: string;
  score: number | null;
}

/** A human label scored by a model that never saw its row. */
export interface Suspect {
  row_id: number;
  given: string;
  /** The out-of-fold probability of the given label. */
  given_probability: number;
  likely: string;
}

export type ExportArtifact =
  | { format: 'dbt'; files: Readonly<Record<string, string>> }
  | { format: Exclude<ExportFormat, 'dbt'>; text: string };

/**
 * What the event stream reports. `connected` follows every (re)connection, after
 * which `/state` is the only record of what was missed; `malformed` is an event
 * that broke this contract.
 */
export type ServerEvent =
  | { kind: 'connected' }
  | { kind: 'disconnected'; retryMs: number }
  | { kind: 'refit_started'; generation: number }
  | { kind: 'progress'; done: number; total: number }
  | { kind: 'refit_done'; generation: number }
  | { kind: 'refit_failed'; failure: ErrorBody }
  | { kind: 'malformed'; failure: ErrorBody };
