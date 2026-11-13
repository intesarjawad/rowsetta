import { describe, expect, it } from 'vitest';
import type { LeafLine } from '../src/backend/types';
import {
  columnDecimals,
  formatThreshold,
  ruleIntervals,
  ruleLineParts,
} from '../src/rule';

describe('threshold formatting', () => {
  it('preserves every digit needed by the SQL boundary', () => {
    expect(formatThreshold('206.50000762939453')).toBe('206.50000762939453');
    expect(formatThreshold('43.35000038146973')).toBe('43.35000038146973');
  });

  it('keeps exact boundaries even when the column uses fewer decimals', () => {
    expect(formatThreshold('206.50000762939453')).toBe('206.50000762939453');
    expect(formatThreshold('3225.0001220703125')).toBe('3225.0001220703125');
    expect(formatThreshold('42.35000038146973')).toBe('42.35000038146973');
  });

  it('leaves text and whole numbers alone', () => {
    expect(formatThreshold("'success'")).toBe("'success'");
    expect(formatThreshold('524')).toBe('524');
  });

  it('reads a column precision off its numeric cells only', () => {
    const places = columnDecimals([
      { bill: 39.1, flipper: 181, island: 'Dream' },
      { bill: 40, flipper: 186.5, island: 'Biscoe' },
    ]);
    expect(places.get('bill')).toBe(1);
    expect(places.get('flipper')).toBe(1);
    expect(places.has('island')).toBe(false);
  });

  it('shows the exact SQL boundary in a rule line', () => {
    const line: LeafLine = {
      line_no: 1,
      conditions: [
        ['flipper_length_mm', 'IS NULL OR <=', '206.50000762939453'],
        ['island', '=', "'Dream'"],
      ],
      label: 'Adelie',
      row_ids: [0],
      agree: { k: 1, n: 1, coverage: { answered: 1, total: 1 } },
    };
    expect(ruleLineParts(line).conditions).toBe(
      '(flipper length ≤ 206.50000762939453 or flipper length is missing) · island is Dream',
    );
  });

  it('merges bounds on one column into an interval', () => {
    expect(
      ruleIntervals([
        ['bill_length_mm', 'IS NULL OR <=', '43.35000038146973'],
        ['bill_length_mm', 'IS NOT NULL AND >', '40.75000190734863'],
        ['bill_length_mm', 'IS NULL OR <=', '42.35000038146973'],
        ['island', 'IS NULL OR <>', "'Dream'"],
      ]),
    ).toBe(
      '40.75000190734863 < bill length ≤ 42.35000038146973 · (island is not Dream or island is missing)',
    );
  });
});

it('shows missing-only routing without a numeric threshold', () => {
  expect(ruleIntervals([['x', 'IS NULL', '']])).toBe('x is missing');
  expect(ruleIntervals([['x', 'IS NOT NULL', '']])).toBe('x is not missing');
});

it('keeps a missing alternative only when every bound permits it', () => {
  expect(
    ruleIntervals([
      ['x', 'IS NULL OR >', '1'],
      ['x', 'IS NULL OR <=', '5'],
    ]),
  ).toBe('(1 < x ≤ 5 or x is missing)');
});

it('simplifies a missing-only branch inside a nullable numeric interval', () => {
  expect(
    ruleIntervals([
      ['x', 'IS NULL OR <=', '5'],
      ['x', 'IS NULL', ''],
    ]),
  ).toBe('x is missing');
});

it('reads exponent notation without losing column precision', () => {
  const places = columnDecimals([
    { x: 1e-8, y: 1.2e-7, z: 1e-100 },
    { x: 1.2e-7, y: 1e21 },
  ]);
  expect(places.get('x')).toBe(8);
  expect(places.get('y')).toBe(8);
  expect(places.get('z')).toBe(100);
});

it.each([
  '48.80000114440918',
  '1e-12',
  '1.2345678901234567',
  '-1e100',
  '5e-324',
])(
  'preserves the double boundary %s regardless of observed precision',
  (value) => {
    expect(Number(formatThreshold(value))).toBe(Number(value));
  },
);
