import type { Cell, Condition, Distilled, LeafLine } from './backend/types';

/** Depths the rule can be fitted at; deeper trees stop reading as a few plain lines. */
export const RULE_DEPTHS = [2, 3, 4, 5, 6] as const;
export const DEFAULT_RULE_DEPTH = 4;

/** Rows the table narrows to, and the words that say why. */
export interface RowFilter {
  rowIds: readonly number[];
  description: string;
}

function decimalPlaces(text: string): number {
  const [mantissa = '', exponent = '0'] = text.toLowerCase().split('e');
  return Math.max(0, (mantissa.split('.')[1]?.length ?? 0) - Number(exponent));
}

/**
 * Column precision includes exponents so small values stay distinct in the table.
 */
export function columnDecimals(
  rows: Iterable<Readonly<Record<string, Cell>>>,
): ReadonlyMap<string, number> {
  const places = new Map<string, number>();
  for (const row of rows) {
    for (const [column, cell] of Object.entries(row)) {
      if (typeof cell !== 'number') continue;
      places.set(
        column,
        Math.max(places.get(column) ?? 0, decimalPlaces(String(cell))),
      );
    }
  }
  return places;
}

/** The shortest decimal text that preserves the SQL boundary as a double. */
export function formatThreshold(value: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? String(number) : value;
}

function floatBits(number: number): bigint {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, number);
  return view.getBigUint64(0);
}

function adjacentFloat(number: number, up: boolean): number {
  if (number === 0) return up ? Number.MIN_VALUE : -Number.MIN_VALUE;
  const view = new DataView(new ArrayBuffer(8));
  view.setBigUint64(0, floatBits(number) + (number > 0 === up ? 1n : -1n));
  return view.getFloat64(0);
}

function floatUnits(number: number): bigint {
  const bits = floatBits(number);
  const exponent = Number((bits >> 52n) & 2047n);
  const mantissa =
    (bits & ((1n << 52n) - 1n)) | (exponent === 0 ? 0n : 1n << 52n);
  const units = mantissa << BigInt(Math.max(0, exponent - 1));
  return bits >> 63n ? -units : units;
}

function floorDivide(value: bigint, divisor: bigint): bigint {
  return value / divisor - (value < 0n && value % divisor !== 0n ? 1n : 0n);
}

export function displayCut(
  value: string,
  strict: boolean,
  places: number | undefined,
): { value: string; strict: boolean } {
  const number = Number(value);
  const exact = { value: formatThreshold(value), strict };
  if (places === undefined || !Number.isFinite(number)) return exact;
  const adjacent = adjacentFloat(number, !strict);
  if (!Number.isFinite(adjacent)) return exact;
  const scale = 10n ** BigInt(places);
  // Units of 2^-1074 give an exact rounding midpoint, even on subnormal grids.
  const midpoint = floatUnits(number) + floatUnits(adjacent);
  let tick = floorDivide(midpoint * scale, 1n << 1075n);
  const grid = (index: bigint, digits = places): number =>
    Number(`${String(index)}e-${String(digits)}`);
  const left = (x: number): boolean => (strict ? x < number : x <= number);
  if (!left(grid(tick))) tick--;
  const low = grid(tick);
  const high = grid(tick + 1n);
  let best = exact;
  let factor = scale;
  for (let digits = 0; digits <= places; digits++, factor /= 10n) {
    const base = floorDivide(tick, factor);
    for (const open of [false, true]) {
      for (const index of [base, base + 1n]) {
        const candidate = grid(index, digits);
        const separates =
          Number.isFinite(candidate) &&
          (open
            ? low < candidate && candidate <= high
            : low <= candidate && candidate < high);
        const text = String(candidate);
        if (
          separates &&
          (text.length < best.value.length ||
            (text.length === best.value.length && best.strict && !open))
        ) {
          best = { value: text, strict: open };
        }
      }
    }
  }
  return best;
}

const UNIT_SUFFIX = /_(?:mm|cm|kg|g|m|s|ms)$/;
const MISSING_PREFIX = /^IS (?:NOT )?NULL (?:OR|AND) /;

interface Bound {
  value: number;
  strict: boolean;
}

/**
 * A rule line's tests as one short phrase per column: the numeric bounds on a
 * column merge into an interval, `flipper length ≤ 206.5 · 40.75 < bill length ≤ 42.35`.
 * Missing alternatives stay explicit when bounds on the same column merge.
 */
export function ruleIntervals(
  conditions: readonly Condition[],
  decimals: ReadonlyMap<string, number> = new Map(),
): string {
  const phrases = new Map<
    string,
    {
      lower?: Bound;
      upper?: Bound;
      words: string[];
      missing: boolean;
      missingOnly: boolean;
    }
  >();
  for (const [column, operator, value] of conditions) {
    const entry = phrases.get(column) ?? {
      words: [],
      missing: true,
      missingOnly: false,
    };
    phrases.set(column, entry);
    if (operator === 'IS NULL') {
      entry.missingOnly = true;
      continue;
    }
    entry.missing &&= operator.startsWith('IS NULL OR ');
    if (operator === 'IS NOT NULL') {
      entry.words.push('is not missing');
      continue;
    }
    const test = operator.replace(MISSING_PREFIX, '');
    let number = Number(value);
    if (['<', '<=', '>', '>='].includes(test) && Number.isFinite(number)) {
      const upper = test === '<=' || test === '<';
      const cut = displayCut(
        value,
        test === '<' || test === '>=',
        decimals.get(column),
      );
      number = Number(cut.value);
      const bound = { value: number, strict: upper ? cut.strict : !cut.strict };
      if (
        upper &&
        (entry.upper === undefined ||
          number < entry.upper.value ||
          (number === entry.upper.value && bound.strict))
      ) {
        entry.upper = bound;
      } else if (
        !upper &&
        (entry.lower === undefined ||
          number > entry.lower.value ||
          (number === entry.lower.value && bound.strict))
      ) {
        entry.lower = bound;
      }
    } else {
      const word = value.replace(/^'|'$/g, '').replace(/''/g, "'");
      entry.words.push(test === '<>' ? `is not ${word}` : `is ${word}`);
    }
  }
  return [...phrases]
    .map(([column, { lower, upper, words, missing, missingOnly }]) => {
      const name = column.replace(UNIT_SUFFIX, '').replaceAll('_', ' ');
      if (missingOnly)
        return missing
          ? `${name} is missing`
          : `${name} has no matching values`;
      const shown = (bound: Bound): string =>
        formatThreshold(String(bound.value));
      const parts = words.map((word) => `${name} ${word}`);
      if (lower !== undefined && upper !== undefined) {
        parts.push(
          `${shown(lower)} ${lower.strict ? '<' : '≤'} ${name} ${upper.strict ? '<' : '≤'} ${shown(upper)}`,
        );
      } else if (upper !== undefined) {
        parts.push(`${name} ${upper.strict ? '<' : '≤'} ${shown(upper)}`);
      } else if (lower !== undefined) {
        parts.push(`${name} ${lower.strict ? '>' : '≥'} ${shown(lower)}`);
      }
      const phrase = parts.join(' · ');
      return missing ? `(${phrase} or ${name} is missing)` : phrase;
    })
    .join(' · ');
}

/** A rule line split into the pieces its text is made of. */
export function ruleLineParts(
  line: LeafLine,
  decimals: ReadonlyMap<string, number> = new Map(),
): {
  conditions: string;
  answer: string | null;
  rows: string;
  agreeing: string;
} {
  return {
    conditions:
      line.conditions.length === 0
        ? 'every row'
        : ruleIntervals(line.conditions, decimals),
    answer: line.label,
    rows: `${String(line.row_ids.length)} rows`,
    agreeing: `${String(line.agree.k)} agree with the model`,
  };
}

/** The line as plain text for the accessible name and plain-text copies. */
export function ruleLineText(
  line: LeafLine,
  decimals: ReadonlyMap<string, number> = new Map(),
): string {
  const { conditions, answer, rows, agreeing } = ruleLineParts(line, decimals);
  if (answer === null)
    return `${conditions} → no answer (rule unsure): ${rows}`;
  return `${conditions} → ${answer}: ${rows}, ${agreeing}`;
}

export function lineFilter(line: LeafLine): RowFilter {
  return {
    rowIds: line.row_ids,
    description: `Showing ${String(line.row_ids.length)} rows for rule line ${String(line.line_no)}`,
  };
}

/** Each row where the rule and the model answer differently, mapped to its line number. */
export function disagreementLines(
  rule: Distilled | null,
): ReadonlyMap<number, number> {
  const found = new Map<number, number>();
  if (rule === null) return found;
  const rows = new Set(rule.disagreements);
  for (const line of rule.leaf_summary) {
    for (const rowId of line.row_ids) {
      if (rows.has(rowId)) found.set(rowId, line.line_no);
    }
  }
  return found;
}
