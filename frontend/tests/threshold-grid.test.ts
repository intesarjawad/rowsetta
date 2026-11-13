import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { Condition, LeafLine } from '../src/backend/types';
import { columnDecimals, ruleIntervals, ruleLineText } from '../src/rule';
import { buildTree, routeOf } from '../src/transit';

const operators = ['<', '<=', '>', '>='] as const;
function compare(x: number, operator: string, cut: number): boolean {
  switch (operator) {
    case '<':
      return x < cut;
    case '<=':
    case '≤':
      return x <= cut;
    case '>':
      return x > cut;
    case '>=':
    case '≥':
      return x >= cut;
    default:
      throw new Error(operator);
  }
}
function shown(text: string): [string, number] {
  const match = /([<>≤≥])\s+(-?[\d.e+]+)/.exec(text);
  if (match === null) throw new Error(text);
  return [match[1] ?? '', Number(match[2])];
}
function check(
  column: string,
  places: number,
  cuts: number[],
  values: number[],
): void {
  const precision = new Map([[column, places]]);
  for (const cut of cuts) {
    for (const operator of operators) {
      const conditions: Condition[] = [[column, operator, String(cut)]];
      const line: LeafLine = {
        line_no: 1,
        conditions,
        label: 'yes',
        row_ids: [0],
        agree: { k: 1, n: 1, coverage: { answered: 1, total: 1 } },
      };
      const text = ruleIntervals(conditions, precision);
      const split = buildTree([line], precision).split;
      if (split === null) throw new Error('Missing split');
      const branch = operator.startsWith('<') ? split.left : split.right;
      const display = shown(text);
      const mapCut = Number(split.cut.split(' ')[0]);
      expect(routeOf([line], 0, precision)?.stops[0]).toContain(
        `${branch} ${split.cut}`,
      );
      expect(ruleLineText(line, precision)).toContain(text);
      const mismatch = values.find(
        (x) =>
          compare(x, operator, cut) !== compare(x, display[0], display[1]) ||
          compare(x, operator, cut) !== compare(x, branch, mapCut),
      );
      expect(
        mismatch,
        `${column} ${operator} ${String(cut)} shown as ${text}`,
      ).toBeUndefined();
      // Adjacent grid values bracket the only transition of each monotone comparison.
      const scale = 10 ** places;
      const near = Math.round(cut * scale);
      for (const tick of [near - 2, near - 1, near, near + 1, near + 2]) {
        const x = Number((tick / scale).toFixed(places));
        expect(compare(x, display[0], display[1])).toBe(
          compare(x, operator, cut),
        );
        expect(compare(x, branch, mapCut)).toBe(compare(x, operator, cut));
      }
      expect(compare(-Number.MAX_VALUE, display[0], display[1])).toBe(
        compare(-Number.MAX_VALUE, operator, cut),
      );
      expect(compare(Number.MAX_VALUE, display[0], display[1])).toBe(
        compare(Number.MAX_VALUE, operator, cut),
      );
      for (let digits = 0; digits < places; digits++) {
        const scale = 10 ** digits;
        const near = Math.round(cut * scale);
        for (const tick of [near - 1, near, near + 1]) {
          const shorter = Number((tick / scale).toFixed(digits));
          if (String(shorter).length >= String(display[1]).length) continue;
          for (const op of operators) {
            expect(
              values.some(
                (x) => compare(x, op, shorter) !== compare(x, operator, cut),
              ),
              `Shorter equivalent: ${op} ${String(shorter)}`,
            ).toBe(true);
          }
        }
      }
    }
  }
}
function grid(start: number, end: number, places: number): number[] {
  const scale = 10 ** places;
  return Array.from({ length: Math.round((end - start) * scale) + 1 }, (_, i) =>
    Number((start + i / scale).toFixed(places)),
  );
}

it('keeps 48.8 on the SQL side of the displayed boundary', () => {
  const precision = new Map([['x', 1]]);
  expect(ruleIntervals([['x', '<', '48.80000114440918']], precision)).toBe(
    'x ≤ 48.8',
  );
  expect(ruleIntervals([['x', '>=', '48.80000114440918']], precision)).toBe(
    'x > 48.8',
  );
  expect(ruleIntervals([['x', '<', '16.65000057220459']], precision)).toBe(
    'x ≤ 16.6',
  );
  check('x', 1, [48.80000114440918, 48.8, 16.65000057220459], grid(15, 50, 1));
});

const csv = readFileSync(
  new URL('../../src/rowsetta/datasets/penguins.csv', import.meta.url),
  'utf8',
)
  .trim()
  .split('\n');
const names = (csv.shift() ?? '').split(',');
const rows = csv.map((line) =>
  Object.fromEntries(
    line
      .split(',')
      .map((value, i) => [
        names[i] ?? '',
        value === 'NA'
          ? null
          : Number.isFinite(Number(value))
            ? Number(value)
            : value,
      ]),
  ),
);
const precision = columnDecimals(rows);
const sql = readFileSync(
  new URL('../../tests/golden/sql/penguins.sqlite.sql', import.meta.url),
  'utf8',
);
describe('decimal-grid comparison equivalence', () => {
  for (const [column, places] of precision) {
    it(`matches SQL for every observed and representable ${column} value`, () => {
      const observed = [
        ...new Set(
          rows
            .map((row) => row[column])
            .filter((x): x is number => typeof x === 'number'),
        ),
      ].sort((a, b) => a - b);
      const cuts = observed.flatMap((value, i) => {
        const next = observed[i + 1];
        return next === undefined
          ? [value]
          : [value, (Math.fround(value) + Math.fround(next)) / 2];
      });
      for (const match of sql.matchAll(
        /"([a-z_]+)"\s*(?:<=|>=|<|>)\s*([\d.]+)/g,
      )) {
        if (match[1] === column) cuts.push(Number(match[2]));
      }
      const min = observed[0] ?? 0;
      const max = observed.at(-1) ?? 0;
      check(column, places, cuts, [
        ...observed,
        ...grid(min - 1, max + 1, places),
      ]);
    });
  }
  let seed = 17629;
  const random = (): number => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
  for (const places of [1, 2, 3]) {
    it(`matches SQL throughout random ${String(places)}-decimal columns`, () => {
      const scale = 10 ** places;
      for (let trial = 0; trial < 30; trial++) {
        const ticks = Array.from({ length: 20 }, () =>
          Math.round((random() * 6 - 3) * scale),
        );
        const observed = ticks.map((tick) => tick / scale);
        const cuts = observed
          .slice(0, 6)
          .flatMap((value, i) => [
            value,
            Math.fround((value + (observed[i + 1] ?? 0)) / 2),
            value + (random() - 0.5) / scale,
          ]);
        check('x', places, cuts, [...observed, ...grid(-4, 4, places)]);
      }
    });
  }
});

it.each([
  [
    16,
    '2.0000000000000004',
    'x ≤ 2',
    [2, 2.0000000000000004, 2.000000000000001],
  ],
  [101, '1e-105', 'x ≤ 0', [-1e-101, 0, 1e-101]],
  [324, '5e-324', 'x ≤ 0', [-5e-324, 0, 5e-324, 1e-323]],
] as const)('shortens cuts on a %s-place grid', (places, cut, text, values) => {
  const precision = new Map([['x', places]]);
  const actual = ruleIntervals([['x', '<', cut]], precision);
  expect(actual).toBe(text);
  const [operator, value] = shown(actual);
  for (const x of values)
    expect(compare(x, operator, value)).toBe(x < Number(cut));
});
