import { describe, expect, it } from 'vitest';
import type { LeafLine } from '../src/backend/types';
import {
  buildTree,
  labelPlace,
  labelShifts,
  overlaps,
  layoutMap,
  legs,
  offsetLine,
  branchSentence,
  clearSpot,
  openSpot,
  restNear,
  restAlong,
  routeOf,
  typeLines,
  typeWidth,
  type Doubt,
  type Rect,
  type Split,
} from '../src/transit';

function line(
  line_no: number,
  conditions: LeafLine['conditions'],
  label: string | null,
  row_ids: number[],
): LeafLine {
  const n = row_ids.length;
  return {
    line_no,
    conditions,
    label,
    row_ids,
    agree: { k: n, n, coverage: { answered: n, total: n } },
  };
}

const FLIPPER = 'flipper_length_mm';
// Three termini: short flippers split again on island, long flippers are Gentoo.
const LINES: LeafLine[] = [
  line(
    1,
    [
      [FLIPPER, 'IS NULL OR <=', '206.50000762939453'],
      ['island', 'IS NULL OR <>', "'Dream'"],
    ],
    'Adelie',
    [0, 1, 2, 3],
  ),
  line(
    2,
    [
      [FLIPPER, 'IS NULL OR <=', '206.50000762939453'],
      ['island', '=', "'Dream'"],
    ],
    'Chinstrap',
    [4, 5],
  ),
  line(
    3,
    [[FLIPPER, 'IS NOT NULL AND >', '206.50000762939453']],
    'Gentoo',
    [6, 7, 8],
  ),
];
const CLASSES = ['Adelie', 'Chinstrap', 'Gentoo'];
const HUMAN = {
  '0': 'Adelie',
  '1': 'Adelie',
  '2': 'Gentoo',
  '3': 'Adelie',
  '4': 'Chinstrap',
  '5': 'Chinstrap',
  '6': 'Gentoo',
  '7': 'Gentoo',
};
const DOUBT: Doubt = {
  row: 2,
  rank: 1,
  given: 'Gentoo',
  likely: 'Adelie',
  probability: 0.01,
};
const BOX = { width: 900, height: 600, labels: 220 };

describe('line map', () => {
  it('rebuilds the tree from its lines, left branch first', () => {
    const root = buildTree(LINES);
    expect(root.split).toMatchObject({
      label: 'flipper length',
      cut: '206.50000762939453 mm',
      left: '≤',
      right: '>',
    });
    expect(root.rows).toHaveLength(9);
    expect(root.children.map((child) => child.key)).toEqual(['L', 'R']);
    expect(root.children[0]?.split).toMatchObject({
      label: 'island',
      cut: 'Dream',
      left: '≠',
      right: '=',
    });
    expect(root.children[0]?.children[1]?.line?.label).toBe('Chinstrap');
  });

  it('runs track only at 0 and 45 degrees and ends every leaf at the terminus line', () => {
    const map = layoutMap(LINES, BOX, HUMAN, {}, CLASSES, [DOUBT]);
    for (const band of map.bands) {
      for (const [[x0, y0], [x1, y1]] of legs(band.points)) {
        const dx = Math.abs(x1 - x0);
        const dy = Math.abs(y1 - y0);
        expect(dy < 1e-6 || Math.abs(dx - dy) < 1e-6).toBe(true);
        expect(x1).toBeGreaterThanOrEqual(x0 - 1e-6);
      }
    }
    expect(map.termini).toHaveLength(3);
    expect(map.termini.every((t) => t.x === BOX.width - BOX.labels)).toBe(true);
  });

  it('draws a doubted row as its own thread and says when it rides the wrong line', () => {
    const map = layoutMap(LINES, BOX, HUMAN, { '8': 'Gentoo' }, CLASSES, [
      DOUBT,
    ]);
    expect(map.wrongLine).toEqual([DOUBT]);
    const adelie = map.termini.find((t) => t.line.label === 'Adelie');
    expect(adelie?.counts).toEqual([
      ['Adelie', 3],
      ['Gentoo', 1],
    ]);
    expect(adelie?.doubts.map((end) => end.doubt.row)).toEqual([2]);
    const proposed = map.bands.find((band) => band.kind === 'proposed');
    expect(proposed).toMatchObject({ cls: 'Gentoo', rows: 1 });
  });

  it('folds a fixed row back into its line', () => {
    const fixed = { ...HUMAN, '2': 'Adelie' };
    const map = layoutMap(LINES, BOX, fixed, {}, CLASSES, [DOUBT]);
    expect(map.wrongLine).toEqual([]);
    expect(map.bands.some((band) => band.doubt !== null)).toBe(false);
  });

  it('keeps parallel bands a fixed distance apart through a 45 degree bend', () => {
    const centre = [
      [0, 0],
      [10, 0],
      [30, 20],
      [50, 20],
    ] as const;
    const moved = offsetLine(centre, 4);
    // Distance from the offset diagonal to the centre diagonal.
    const [, [ax, ay] = [NaN, NaN], [bx, by] = [NaN, NaN]] = moved;
    expect(by - ay).toBeCloseTo(bx - ax);
    expect(Math.abs(ax - ay - (10 - 0)) / Math.SQRT2).toBeCloseTo(4);
    expect(moved[0]?.[1]).toBeCloseTo(4);
    expect(moved[3]?.[1]).toBeCloseTo(24);
  });

  it('reads a row route as the branch each interchange sends it down', () => {
    expect(routeOf(LINES, 5)?.stops).toEqual([
      'flipper length ≤ 206.50000762939453 mm',
      'island = Dream',
    ]);
    expect(routeOf(LINES, 6)?.terminus.label).toBe('Gentoo');
    expect(routeOf(LINES, 99)).toBeNull();
  });

  it('stacks the signs in the fork, centred in the gap, the name before the capsule', () => {
    const wide = labelPlace({ x: 100, y: 200 }, 80, 80, 20, 10);
    expect(wide.up[0]).toBe(wide.down[0]);
    expect(wide.up[1]).toBeLessThan(wide.down[1]);
    // A 20 px band at 45 degrees spans 28 px vertically, so the signs clear it past 18 + 29.1.
    expect(wide.up[0]).toBeGreaterThan(100 + 18 + 20 * Math.SQRT1_2 + 15);
    expect(wide.name[0]).toBeLessThan(100);

    // Branches that level off early: the signs sit midway between the level bands.
    const early = labelPlace({ x: 100, y: 200 }, 20, 24, 4, 6);
    const gapTop = 200 - 20 + 2;
    const gapBottom = 200 + 24 - 3;
    expect((early.up[1] + 3 + early.down[1] - 11) / 2).toBeCloseTo(
      (gapTop + gapBottom) / 2,
    );
    expect(early.up[0]).toBeGreaterThan(100 + 18 + 24);
  });

  it('sets no station type over another, and all of it short of the roundel column', () => {
    const map = layoutMap(LINES, { ...BOX, type: true }, HUMAN, {}, CLASSES, [
      DOUBT,
    ]);
    const boxes = map.stations.flatMap((station): Rect[] => {
      const [name, upper, lower] = typeLines(station.split, station.upLeft).map(
        typeWidth,
      );
      const { label } = station;
      return [
        [
          label.name[0] - (name ?? 0),
          label.name[1] - 11,
          label.name[0],
          label.name[1] + 3,
        ],
        [
          label.up[0],
          label.up[1] - 11,
          label.up[0] + (upper ?? 0),
          label.up[1] + 3,
        ],
        [
          label.down[0],
          label.down[1] - 11,
          label.down[0] + (lower ?? 0),
          label.down[1] + 3,
        ],
      ];
    });
    boxes.forEach((a, i) => {
      expect(a[2]).toBeLessThanOrEqual(map.terminusX - 24);
      boxes.slice(i + 1).forEach((b) => {
        const apart =
          a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1];
        expect(apart).toBe(true);
      });
    });
  });

  it('keeps strict comparisons for every column precision', () => {
    const split = (value: string): Split | null =>
      buildTree([
        line(1, [['bill_depth_mm', '<', value]], 'Gentoo', [0]),
        line(2, [['bill_depth_mm', '>=', value]], 'Adelie', [1]),
      ]).split;
    expect(split('48.8')).toMatchObject({
      left: '<',
      right: '≥',
      cut: '48.8 mm',
    });
    expect(split('16.65')).toMatchObject({
      left: '<',
      right: '≥',
      cut: '16.65 mm',
    });
    expect(split('48.8')).toMatchObject({ left: '<', right: '≥' });
    expect(buildTree(LINES).children[0]?.split).toMatchObject({
      label: 'island',
      cut: 'Dream',
      left: '≠',
      right: '=',
    });
  });

  it('rests the glass where its route crosses it clear of every box, else on open white', () => {
    const route: [number, number][] = [
      [0, 100],
      [400, 100],
    ];
    const half = [40, 30] as const;
    const size = [400, 300] as const;
    // A station sits on the route's middle: the glass slides off it, keeping the route inside.
    const station: [number, number, number, number] = [180, 80, 220, 120];
    const at = restNear(route, half, [station], size);
    expect(at).not.toBeNull();
    const [x = 0, y = 0] = at ?? [];
    expect(Math.abs(y - 100)).toBeLessThanOrEqual(30 - 24 + 8);
    expect(
      x + 40 <= 180 || x - 40 >= 220 || y + 30 <= 80 || y - 30 >= 120,
    ).toBe(true);
    // The whole route blocked: open white below it.
    const band: [number, number, number, number] = [0, 40, 400, 160];
    const open = restNear(route, half, [band], size);
    expect(open?.[1]).toBeGreaterThanOrEqual(190);
    expect(openSpot([200, 100], half, [[0, 0, 400, 300]], size)).toBeNull();
    const track = {
      key: 't',
      points: route,
      width: 20,
      cls: null,
      kind: 'none' as const,
      doubt: null,
      rows: 1,
    };
    const white = openSpot([200, 100], half, [], size, [track]);
    expect(Math.abs((white?.[1] ?? 100) - 100)).toBeGreaterThanOrEqual(44);
  });

  it('says which way a station sends rows in plain words', () => {
    const number = {
      column: 'bill_length_mm',
      label: 'bill length',
      cut: '43.35 mm',
      left: '≤',
      right: '>',
    };
    expect(branchSentence(number, true)).toBe(
      'Rows with bill length up to 43.35 mm go up, the rest go down.',
    );
    expect(branchSentence(number, false)).toBe(
      'Rows with bill length up to 43.35 mm go down, the rest go up.',
    );
    const place = {
      column: 'island',
      label: 'island',
      cut: 'Biscoe',
      left: '≠',
      right: '=',
    };
    expect(branchSentence(place, true)).toBe(
      'Rows with island Biscoe go down, the rest go up.',
    );
  });

  it('rests the glass mid-route, moving along it to clear what must stay in view', () => {
    const route: [number, number][] = [
      [0, 100],
      [400, 100],
    ];
    const half = [40, 30] as const;
    const size = [400, 200] as const;
    expect(restAlong(route, half, [], size)?.at).toEqual([200, 100]);

    const along = restAlong(route, half, [[150, 0, 250, 200]], size);
    expect(along?.at[0]).toBeCloseTo(0.26 * 400);
    expect(along?.at[1]).toBe(100);

    const across = restAlong(route, half, [[0, 40, 400, 72]], size);
    expect(across?.at).toEqual([200, 107.5]);

    expect(restAlong(route, half, [[0, 0, 400, 200]], size)).toBeNull();

    // Scored, it takes the passing point with the most map under it.
    const inked = restAlong(
      route,
      half,
      [],
      size,
      false,
      ([x]) => -Math.abs(x - 300),
    );
    expect(inked?.at[0]).toBeCloseTo(0.74 * 400);
    expect(inked?.at[1]).toBe(100);
  });

  it('settles the glass on the nearest stretch of track clear of every box', () => {
    const track: [number, number][] = [
      [0, 100],
      [400, 100],
    ];
    const half = [40, 30] as const;
    const size = [400, 300] as const;
    const open = clearSpot([200, 0], half, [], [track], size);
    expect(open?.[1]).toBe(100);
    expect(Math.abs((open?.[0] ?? 0) - 200)).toBeLessThan(6);
    const spot = clearSpot([240, 0], half, [[150, 0, 260, 300]], [track], size);
    expect(spot?.[1]).toBe(100);
    expect(spot?.[0]).toBeGreaterThanOrEqual(300);
    expect(
      clearSpot([200, 0], half, [[0, 0, 400, 300]], [track], size),
    ).toBeNull();
  });
});

it.each(['<', '<=', '>', '>='] as const)(
  'map and text preserve SQL %s at and around the boundary',
  (operator) => {
    const boundary = '48.80000114440918';
    const conditions: LeafLine['conditions'] = [['x', operator, boundary]];
    const lines = [line(1, conditions, 'a', [0])];
    const map = buildTree(lines).split;
    expect(map).not.toBeNull();
    const symbol = operator.startsWith('<') ? map?.left : map?.right;
    expect(symbol).toBe(operator.replace('<=', '≤').replace('>=', '≥'));
    expect(Number(map?.cut)).toBe(Number(boundary));
    expect(routeOf(lines, 0)?.stops).toEqual([`x ${symbol ?? ''} ${boundary}`]);
    const compare = (x: number, op: string, cut: number): boolean => {
      switch (op) {
        case '<':
          return x < cut;
        case '≤':
        case '<=':
          return x <= cut;
        case '>':
          return x > cut;
        case '≥':
        case '>=':
          return x >= cut;
        default:
          throw new Error(op);
      }
    };
    for (const input of [
      48.7,
      48.8,
      Number(boundary) - 1e-14,
      Number(boundary),
      Number(boundary) + 1e-14,
      48.9,
    ]) {
      expect(compare(input, symbol ?? '', Number(map?.cut))).toBe(
        compare(input, operator, Number(boundary)),
      );
    }
  },
);

it('keeps neighbouring readings separate when the glass displaces them', () => {
  const glass: Rect = [100, 100, 300, 220];
  const boxes: Rect[] = [
    [80, 110, 280, 128],
    [120, 150, 320, 168],
    [90, 190, 290, 208],
    [110, 240, 310, 258],
  ];
  const shifts = labelShifts(boxes, glass, 400);
  const moved = boxes.map((box, index): Rect => [
    box[0],
    box[1] + (shifts[index] ?? 0),
    box[2],
    box[3] + (shifts[index] ?? 0),
  ]);
  for (const [index, box] of moved.entries()) {
    expect(overlaps(box, glass)).toBe(false);
    for (const other of moved.slice(index + 1))
      expect(overlaps(box, other)).toBe(false);
  }
  expect(shifts[3]).toBe(0);
});
