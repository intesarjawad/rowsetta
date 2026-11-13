import {
  COLUMN_KINDS,
  LEAK_KINDS,
  type Cell,
  type ColumnInfo,
  type Condition,
  type Distilled,
  type ErrorBody,
  type Evaluation,
  type LeafLine,
  type LeakHint,
  type Measured,
  type NeedsRows,
  type Suspect,
  type TablePage,
  type WorkspaceState,
} from './types';

/** A response that parsed as JSON but does not have the declared shape. */
export class DecodeError extends Error {
  constructor(path: string, expected: string) {
    super(`${path}: expected ${expected}`);
    this.name = 'DecodeError';
  }
}

type Decoder<T> = (value: unknown, path: string) => T;
type Read = <T>(key: string, decode: Decoder<T>) => T;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function object(value: unknown, path: string): Record<string, unknown> {
  if (!isObject(value)) throw new DecodeError(path, 'an object');
  return value;
}

function reader(value: unknown, path: string): Read {
  const body = object(value, path);
  return (key, decode) => decode(body[key], `${path}.${key}`);
}

function string(value: unknown, path: string): string {
  if (typeof value !== 'string') throw new DecodeError(path, 'a string');
  return value;
}

function number(value: unknown, path: string): number {
  if (typeof value !== 'number') throw new DecodeError(path, 'a number');
  return value;
}

function integer(value: unknown, path: string): number {
  if (!Number.isInteger(value)) throw new DecodeError(path, 'an integer');
  return number(value, path);
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') throw new DecodeError(path, 'a boolean');
  return value;
}

function cell(value: unknown, path: string): Cell {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return value;
  }
  throw new DecodeError(path, 'a string, number, boolean or null');
}

function nullable<T>(decode: Decoder<T>): Decoder<T | null> {
  return (value, path) => (value === null ? null : decode(value, path));
}

function arrayOf<T>(decode: Decoder<T>): Decoder<T[]> {
  return (value, path) => {
    if (!Array.isArray(value)) throw new DecodeError(path, 'an array');
    return value.map((item: unknown, index) =>
      decode(item, `${path}[${String(index)}]`),
    );
  };
}

function recordOf<T>(decode: Decoder<T>): Decoder<Record<string, T>> {
  return (value, path) =>
    Object.fromEntries(
      Object.entries(object(value, path)).map(([key, item]) => [
        key,
        decode(item, `${path}.${key}`),
      ]),
    );
}

function oneOf<const T extends readonly string[]>(
  values: T,
): Decoder<T[number]> {
  return (value, path) => {
    const match = values.find((candidate) => candidate === value);
    if (match === undefined) throw new DecodeError(path, values.join(' | '));
    return match;
  };
}

export function errorBody(value: unknown, path: string): ErrorBody {
  const read = reader(value, path);
  const body: ErrorBody = {
    error: read('error', string),
    next_step: read('next_step', string),
  };
  const missing = read('missing', (raw, at) =>
    raw === undefined ? undefined : recordOf(integer)(raw, at),
  );
  if (missing !== undefined) body.missing = missing;
  return body;
}

function measurement(value: unknown, path: string): Measured | NeedsRows {
  const read = reader(value, path);
  const kind = read('kind', oneOf(['measured', 'needs_rows'] as const));
  if (kind === 'needs_rows') {
    return { kind, counts: read('counts', recordOf(integer)) };
  }
  return {
    kind,
    value: read('value', number),
    lo: read('lo', number),
    hi: read('hi', number),
  };
}

function measured(value: unknown, path: string): Measured {
  const result = measurement(value, path);
  if (result.kind !== 'measured')
    throw new DecodeError(`${path}.kind`, 'measured');
  return result;
}

function evaluation(value: unknown, path: string): Evaluation {
  const read = reader(value, path);
  return {
    n: read('n', integer),
    accuracy: read('accuracy', measured),
    balanced_accuracy: read('balanced_accuracy', measurement),
    per_class_recall: read('per_class_recall', recordOf(nullable(number))),
    majority_class: read('majority_class', string),
    majority_baseline: read('majority_baseline', number),
  };
}

export function workspaceState(value: unknown, path: string): WorkspaceState {
  const read = reader(value, path);
  return {
    loaded: read('loaded', boolean),
    file_name: read('file_name', (raw, at) =>
      raw === undefined ? null : nullable(string)(raw, at),
    ),
    notice: read('notice', nullable(string)),
    target: read('target', nullable(string)),
    classes: read('classes', arrayOf(string)),
    human: read('human', recordOf(string)),
    eval_count: read('eval_count', integer),
    threshold: read('threshold', number),
    excluded_columns: read('excluded_columns', arrayOf(string)),
    generation: read('generation', integer),
    refit_generation: read('refit_generation', nullable(integer)),
    proposals: read('proposals', recordOf(string)),
    confidence: read('confidence', recordOf(number)),
    abstained: read('abstained', arrayOf(integer)),
    missing: read('missing', recordOf(integer)),
    next_row: read('next_row', nullable(integer)),
    evaluation: read('evaluation', nullable(evaluation)),
    failure: read('failure', nullable(errorBody)),
    dev_states: read('dev_states', boolean),
  };
}

function columnInfo(value: unknown, path: string): ColumnInfo {
  const read = reader(value, path);
  return {
    name: read('name', string),
    kind: read('kind', oneOf(COLUMN_KINDS)),
    distinct_ratio: read('distinct_ratio', number),
    missing_ratio: read('missing_ratio', number),
  };
}

export function tablePage(value: unknown, path: string): TablePage {
  const read = reader(value, path);
  return {
    rows: read('rows', arrayOf(recordOf(cell))),
    row_ids: read('row_ids', arrayOf(integer)),
    columns: read('columns', arrayOf(columnInfo)),
    total: read('total', integer),
    source_rows: read('source_rows', integer),
    page: read('page', integer),
    size: read('size', integer),
  };
}

export function nextEvalRow(value: unknown, path: string): number | null {
  return reader(value, path)('row_id', nullable(integer));
}

function condition(value: unknown, path: string): Condition {
  const [column, operator, operand, ...rest] = arrayOf(string)(value, path);
  if (
    column === undefined ||
    operator === undefined ||
    operand === undefined ||
    rest.length > 0
  ) {
    throw new DecodeError(path, '[column, operator, value]');
  }
  return [column, operator, operand];
}

function coverage(value: unknown, path: string): LeafLine['agree']['coverage'] {
  const read = reader(value, path);
  return { answered: read('answered', integer), total: read('total', integer) };
}

function agreement(value: unknown, path: string): LeafLine['agree'] {
  const read = reader(value, path);
  return {
    k: read('k', integer),
    n: read('n', integer),
    coverage: read('coverage', coverage),
  };
}

function leafLine(value: unknown, path: string): LeafLine {
  const read = reader(value, path);
  return {
    line_no: read('line_no', integer),
    conditions: read('conditions', arrayOf(condition)),
    label: read('label', nullable(string)),
    row_ids: read('row_ids', arrayOf(integer)),
    agree: read('agree', agreement),
  };
}

export function distilled(value: unknown, path: string): Distilled {
  const read = reader(value, path);
  return {
    leaf_summary: read('leaf_summary', arrayOf(leafLine)),
    disagreements: read('disagreements', arrayOf(integer)),
    generation: read('generation', integer),
  };
}

function leakHint(value: unknown, path: string): LeakHint {
  const read = reader(value, path);
  return {
    column: read('column', string),
    kind: read('kind', oneOf(LEAK_KINDS)),
    reason: read('reason', string),
    score: read('score', nullable(number)),
  };
}

export function leaks(value: unknown, path: string): LeakHint[] {
  return reader(value, path)('leaks', arrayOf(leakHint));
}

function suspect(value: unknown, path: string): Suspect {
  const read = reader(value, path);
  return {
    row_id: read('row_id', integer),
    given: read('given', string),
    given_probability: read('given_probability', number),
    likely: read('likely', string),
  };
}

export function suspects(value: unknown, path: string): Suspect[] {
  return reader(value, path)('suspects', arrayOf(suspect));
}

export function health(value: unknown, path: string): boolean {
  return reader(value, path)('ok', boolean);
}

export function generation(value: unknown, path: string): number {
  return reader(value, path)('generation', integer);
}

export function progress(
  value: unknown,
  path: string,
): { done: number; total: number } {
  const read = reader(value, path);
  return { done: read('done', integer), total: read('total', integer) };
}

export const dbtFiles: (
  value: unknown,
  path: string,
) => Record<string, string> = recordOf(string);
