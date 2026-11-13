import type { ByRow, Condition, LeafLine } from './backend/types';
import { displayCut } from './rule';

/**
 * The fitted rule drawn as a line map, after Vignelli's 1972 subway diagram:
 * every row enters at the origin and rides the splits to a terminus, track runs
 * only at 0 and 45 degrees, and a band's width is the rows it carries.
 */

export type Point = readonly [number, number];

export interface Split {
  column: string;
  /** The column as people read it: no unit suffix, spaces for underscores. */
  label: string;
  /** The cut with its unit, such as `206.5 mm`, or the category, such as `Biscoe`. */
  cut: string;
  /** The sign each branch takes against the cut: `≤` and `>`, or `≠` and `=`. */
  left: string;
  right: string;
}

export interface TransitNode {
  /** The branch path from the origin: `''`, `'L'`, `'LR'` and so on. */
  key: string;
  depth: number;
  rows: readonly number[];
  split: Split | null;
  children: TransitNode[];
  /** Set on termini only. */
  line: LeafLine | null;
  x: number;
  y: number;
}

/** A row the audit doubts, drawn as its own thread so it shows on the line it rides. */
export interface Doubt {
  row: number;
  /** 1 is the label the model believes least. */
  rank: number;
  given: string;
  likely: string;
  probability: number;
}

export type Kind = 'human' | 'proposed' | 'none';

/** One stroked band of track: a class's rows on one stretch, or one doubted row. */
export interface Band {
  key: string;
  points: readonly Point[];
  width: number;
  cls: string | null;
  kind: Kind;
  /** Set when the band is a doubted row's thread. */
  doubt: Doubt | null;
  rows: number;
}

/**
 * Where a station's type sits: its test named once, ending just before the
 * capsule, and the sign each branch takes where that branch leaves.
 */
export interface Label {
  name: Point;
  up: Point;
  down: Point;
}

export interface Station {
  key: string;
  x: number;
  y: number;
  /** The capsule's half height, so labels clear the bundle. */
  half: number;
  split: Split;
  rows: number;
  upLeft: boolean;
  label: Label;
}

export interface Terminus {
  key: string;
  x: number;
  y: number;
  half: number;
  line: LeafLine;
  /** Rows reaching it by the label they carry, largest first. */
  counts: readonly (readonly [string, number])[];
  /** Doubted rows that end here, in rank order, with each one's thread centre. */
  doubts: readonly { doubt: Doubt; y: number }[];
}

export interface TransitMap {
  width: number;
  height: number;
  bands: readonly Band[];
  stations: readonly Station[];
  termini: readonly Terminus[];
  /** Rows per pixel of band width, for the caption. */
  rowsPerPx: number;
  /** Doubted rows whose label differs from the terminus they reach. */
  wrongLine: readonly Doubt[];
  origin: Point;
  /** x where termini sit and where their names start. */
  terminusX: number;
}

const UNIT_SUFFIX = /_(?:mm|cm|kg|g|m|s|ms)$/;
const UNIT = /_(mm|cm|kg|g|m|s|ms)$/;
const MISSING_PREFIX = /^IS (?:NOT )?NULL (?:OR|AND) /;

/** True for the test a split sends left: `<=`, `<` or a categorical `<>`. */
function goesLeft(condition: Condition): boolean {
  const test = condition[1].replace(MISSING_PREFIX, '');
  return test === '<=' || test === '<' || test === '<>';
}

/** A column as people read it, and its unit: `bill_length_mm` is `bill length`, `mm`. */
export function columnWords(column: string): [string, string | undefined] {
  return [
    column.replace(UNIT_SUFFIX, '').replaceAll('_', ' '),
    UNIT.exec(column)?.[1],
  ];
}

function splitOf(
  condition: Condition,
  decimals: ReadonlyMap<string, number>,
): Split {
  const [column, operator, value] = condition;
  const [name, unit] = columnWords(column);
  const test = operator.replace(MISSING_PREFIX, '');
  if (test === '<>' || test === '=') {
    const word = value.replace(/^'|'$/g, '').replace(/''/g, "'");
    return { column, label: name, cut: word, left: '≠', right: '=' };
  }
  const { value: cut, strict } = displayCut(
    value,
    test === '<' || test === '>=',
    decimals.get(column),
  );
  return {
    column,
    label: name,
    cut: unit === undefined ? cut : `${cut} ${unit}`,
    left: strict ? '<' : '≤',
    right: strict ? '≥' : '>',
  };
}

/** Rebuild the tree from its root-to-leaf lines, which arrive left to right. */
export function buildTree(
  lines: readonly LeafLine[],
  decimals: ReadonlyMap<string, number> = new Map(),
): TransitNode {
  const node = (key: string): TransitNode => ({
    key,
    depth: key.length,
    rows: [],
    split: null,
    children: [],
    line: null,
    x: 0,
    y: 0,
  });
  const root = node('');
  for (const line of lines) {
    let at = root;
    (at.rows as number[]).push(...line.row_ids);
    for (const condition of line.conditions) {
      at.split ??= splitOf(condition, decimals);
      const side = goesLeft(condition) ? 'L' : 'R';
      let next = at.children.find((child) => child.key.endsWith(side));
      if (next === undefined) {
        next = node(at.key + side);
        at.children.push(next);
        at.children.sort((a, b) => a.key.localeCompare(b.key));
      }
      at = next;
      (at.rows as number[]).push(...line.row_ids);
    }
    at.line = line;
  }
  return root;
}

export function leavesOf(root: TransitNode): TransitNode[] {
  return root.children.length === 0 ? [root] : root.children.flatMap(leavesOf);
}

function walk(root: TransitNode): TransitNode[] {
  return [root, ...root.children.flatMap(walk)];
}

/** Each consecutive pair of points: the legs of a line. */
export function legs(points: readonly Point[]): [Point, Point][] {
  const out: [Point, Point][] = [];
  let previous: Point | undefined;
  for (const point of points) {
    if (previous !== undefined) out.push([previous, point]);
    previous = point;
  }
  return out;
}

/** The point on a polyline nearest to `p`, and how far away it is. */
export function nearestOn(
  points: readonly Point[],
  p: Point,
): { at: Point; distance: number } | null {
  let best: { at: Point; distance: number } | null = null;
  for (const [a, b] of legs(points)) {
    const [dx, dy] = [b[0] - a[0], b[1] - a[1]];
    const f = Math.max(
      0,
      Math.min(
        1,
        ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1),
      ),
    );
    const at: Point = [a[0] + dx * f, a[1] + dy * f];
    const distance = Math.hypot(at[0] - p[0], at[1] - p[1]);
    if (best === null || distance < best.distance) best = { at, distance };
  }
  return best;
}

export function offsetLine(points: readonly Point[], offset: number): Point[] {
  const normal = (a: Point, b: Point): Point => {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const length = Math.hypot(dx, dy) || 1;
    return [-dy / length, dx / length];
  };
  return points.map((point, index) => {
    const previous = points[index - 1];
    const next = points[index + 1];
    const before = previous === undefined ? null : normal(previous, point);
    const after = next === undefined ? null : normal(point, next);
    const a = before ?? after ?? [0, 0];
    const b = after ?? before ?? [0, 0];
    const scale = offset / (1 + a[0] * b[0] + a[1] * b[1]);
    return [point[0] + (a[0] + b[0]) * scale, point[1] + (a[1] + b[1]) * scale];
  });
}

export interface Box {
  width: number;
  height: number;
  /** Space kept on the right for terminus names. */
  labels: number;
  /** Set station type beside the track, and leave the room it needs. */
  type?: boolean;
}

interface Group {
  key: string;
  cls: string | null;
  kind: Kind;
  rows: number[];
  doubt: Doubt | null;
}

const STUB = 18;
const MIN_RUN = 36;
const GAP = 1.5;
const MIN_BAND = 2;
const THREAD = 2.5;
const PAD = 24;
/** Rank roundels stand in a column this far before the terminus bar; type stops short of it. */
const ROUNDELS = 48;

/** A station's type: its test, named once, then the sign on the upper branch and on the lower. */
export function typeLines(
  split: Split,
  upLeft: boolean,
): [string, string, string] {
  const [upper, lower] = upLeft
    ? [split.left, split.right]
    : [split.right, split.left];
  return [`${split.label} ${split.cut}`, upper, lower];
}

/** Which way a station sends rows, in words: "Rows with bill length up to 43.35 mm go up, the rest go down." */
export function branchSentence(split: Split, upLeft: boolean): string {
  const [, upper] = typeLines(split, upLeft);
  const named = [split.left, split.right].includes('=') ? '=' : split.left;
  const test =
    named === '='
      ? split.cut
      : `${named === '<' ? 'under' : 'up to'} ${split.cut}`;
  const [first, rest] = upper === named ? ['up', 'down'] : ['down', 'up'];
  return `Rows with ${split.label} ${test} go ${first}, the rest go ${rest}.`;
}

/** The width 12 px type takes, near enough to keep it clear of things. */
export const typeWidth = (text: string): number => text.length * 6.4 + 6;

/**
 * Lay the rule out as a line map in `box`. Each row takes its colour from the
 * label it carries: a person's label in full colour, a model proposal paler,
 * none in grey. Doubted rows that still carry the doubted label ride as threads.
 */
export function layoutMap(
  lines: readonly LeafLine[],
  box: Box,
  human: ByRow<string>,
  proposals: ByRow<string>,
  classes: readonly string[],
  doubts: readonly Doubt[],
  decimals: ReadonlyMap<string, number> = new Map(),
): TransitMap {
  const root = buildTree(lines, decimals);
  const leaves = leavesOf(root);
  const open = new Map(
    doubts
      .filter((doubt) => human[String(doubt.row)] === doubt.given)
      .map((doubt) => [doubt.row, doubt]),
  );
  const total = Math.max(root.rows.length, 1);
  const largestLeaf = Math.max(...leaves.map((leaf) => leaf.rows.length), 1);

  // Fit vertically first, then shrink until the 45 degree runs fit the width.
  let height = box.height - PAD * 2;
  let nodes = walk(root);
  const terminusX = box.width - box.labels;
  for (let attempt = 0; attempt < 6; attempt++) {
    const slot = height / leaves.length;
    leaves.forEach((leaf, index) => {
      leaf.y = PAD + (box.height - PAD * 2 - height) / 2 + slot * (index + 0.5);
    });
    const place = (node: TransitNode): number => {
      if (node.children.length === 0) return node.y;
      const ys = node.children.map(place);
      node.y = ys.reduce((sum, y) => sum + y, 0) / ys.length;
      return node.y;
    };
    place(root);
    root.x =
      PAD +
      Math.max(
        120,
        root.split === null
          ? 0
          : Math.min(
              typeWidth(typeLines(root.split, true)[0]) + 12,
              (terminusX - PAD) / 2,
            ),
      );
    const across = (node: TransitNode): void => {
      for (const child of node.children) {
        child.x = node.x + STUB * 2 + Math.abs(child.y - node.y);
        across(child);
      }
    };
    across(root);
    nodes = walk(root);
    const widest = Math.max(
      ...nodes.filter((n) => n.children.length > 0).map((n) => n.x),
      ...leaves.map((leaf) => leaf.x - STUB),
    );
    // A station's signs sit past its fork, so the column needs room for them too.
    const typeEnd = box.type
      ? Math.max(
          0,
          ...nodes.map((node) => {
            if (node.split === null) return 0;
            const run = Math.max(
              ...node.children.map((child) => Math.abs(child.y - node.y)),
            );
            return node.x + STUB + run + 6 + typeWidth('≤');
          }),
        )
      : 0;
    if (widest + MIN_RUN <= terminusX && typeEnd + ROUNDELS <= terminusX) break;
    height *= Math.max(
      0.5,
      Math.min(
        (terminusX - MIN_RUN - root.x) / (widest - root.x),
        typeEnd === 0
          ? 1
          : (terminusX - ROUNDELS - root.x) / (typeEnd - root.x),
      ),
    );
  }

  const slot = height / leaves.length;
  const rowPx = Math.min(
    0.2,
    (slot * 0.6) / largestLeaf,
    (height * 0.12) / total,
  );

  const colourOf = (row: number): { cls: string | null; kind: Kind } => {
    const given = human[String(row)];
    if (given !== undefined) return { cls: given, kind: 'human' };
    const proposed = proposals[String(row)];
    if (proposed !== undefined) return { cls: proposed, kind: 'proposed' };
    return { cls: null, kind: 'none' };
  };
  const order = [...classes];
  const groupsOf = (rows: readonly number[]): Group[] => {
    const plain = new Map<string, Group>();
    const threads: Group[] = [];
    for (const row of rows) {
      const doubt = open.get(row);
      const { cls, kind } = colourOf(row);
      if (doubt !== undefined) {
        threads.push({
          key: `row${String(row)}`,
          cls,
          kind,
          rows: [row],
          doubt,
        });
        continue;
      }
      const key = `${kind}:${cls ?? ''}`;
      const group = plain.get(key) ?? { key, cls, kind, rows: [], doubt: null };
      group.rows.push(row);
      plain.set(key, group);
    }
    const rank = (group: Group): number =>
      (group.cls === null ? order.length : order.indexOf(group.cls)) * 3 +
      ['human', 'proposed', 'none'].indexOf(group.kind);
    threads.sort((a, b) => (a.doubt?.rank ?? 0) - (b.doubt?.rank ?? 0));
    return [
      ...[...plain.values()].sort((a, b) => rank(a) - rank(b)),
      ...threads,
    ];
  };
  const widthOf = (group: Group): number =>
    group.doubt !== null
      ? THREAD
      : Math.max(MIN_BAND, group.rows.length * rowPx);
  const thickness = (groups: readonly Group[]): number =>
    groups.reduce((sum, group) => sum + widthOf(group), 0) +
    Math.max(groups.length - 1, 0) * GAP;

  const bands: Band[] = [];
  const lay = (
    key: string,
    centre: readonly Point[],
    groups: Group[],
  ): void => {
    let at = -thickness(groups) / 2;
    for (const group of groups) {
      const width = widthOf(group);
      bands.push({
        key: `${key}|${group.key}`,
        points: offsetLine(centre, at + width / 2),
        width,
        cls: group.cls,
        kind: group.kind,
        doubt: group.doubt,
        rows: group.rows.length,
      });
      at += width + GAP;
    }
  };

  const origin: Point = [PAD, root.y];
  lay('in', [origin, [root.x, root.y]], groupsOf(root.rows));
  const stations: Station[] = [];
  const termini: Terminus[] = [];
  const settle: {
    station: Station;
    choices: ReturnType<typeof labelChoices>;
    widths: number[];
  }[] = [];
  for (const node of nodes) {
    for (const child of node.children) {
      const end = child.children.length === 0 ? terminusX : child.x;
      const turn = node.x + STUB;
      lay(
        child.key,
        [
          [node.x, node.y],
          [turn, node.y],
          [turn + Math.abs(child.y - node.y), child.y],
          [end, child.y],
        ],
        groupsOf(child.rows),
      );
    }
    const groups = groupsOf(node.rows);
    const half = Math.max(8, thickness(groups) / 2 + 4);
    if (node.split !== null) {
      const [up, down] = [...node.children].sort((a, b) => a.y - b.y);
      const upLeft = node.children[0] !== undefined && node.children[0] === up;
      const widths = typeLines(node.split, upLeft).map(typeWidth);
      const parent = nodes.find((other) => other.children.includes(node));
      const choices = labelChoices(
        node,
        up === undefined ? 0 : node.y - up.y,
        down === undefined ? 0 : down.y - node.y,
        up === undefined ? 0 : thickness(groupsOf(up.rows)),
        down === undefined ? 0 : thickness(groupsOf(down.rows)),
        thickness(groups),
        parent !== undefined && parent.y < node.y,
      );
      const station: Station = {
        label: choices[0],
        key: node.key,
        x: node.x,
        y: node.y,
        half,
        split: node.split,
        rows: node.rows.length,
        upLeft,
      };
      stations.push(station);
      settle.push({ station, choices, widths });
    } else if (node.line !== null) {
      const counts = new Map<string, number>();
      for (const row of node.rows) {
        const cls = colourOf(row).cls ?? 'no label';
        counts.set(cls, (counts.get(cls) ?? 0) + 1);
      }
      let at = node.y - thickness(groups) / 2;
      const ends: { doubt: Doubt; y: number }[] = [];
      for (const group of groups) {
        const width = widthOf(group);
        if (group.doubt !== null)
          ends.push({ doubt: group.doubt, y: at + width / 2 });
        at += width + GAP;
      }
      termini.push({
        key: node.key,
        x: terminusX,
        y: node.y,
        half,
        line: node.line,
        counts: [...counts].sort((a, b) => b[1] - a[1]),
        doubts: ends,
      });
    }
  }

  // With all the track laid, each station takes the first placement of its type
  // that clears the track, the capsules, the roundel column and type already set.
  const trunkTop = origin[1] - thickness(groupsOf(root.rows)) / 2;
  const taken: Rect[] = [
    [terminusX - ROUNDELS, -Infinity, Infinity, Infinity],
    [-Infinity, -Infinity, 0, Infinity],
    [0, -Infinity, box.width, 16],
    [0, box.height - 76, origin[0] + 350, box.height],
    // The row count over the origin.
    [origin[0], trunkTop - 24, origin[0] + 80, trunkTop - 6],
  ];
  for (const band of bands) {
    const reach = band.width / 2 + 2;
    for (const [a, b] of legs(band.points)) {
      const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (a[1] === b[1]) {
        taken.push([
          Math.min(a[0], b[0]),
          a[1] - reach,
          Math.max(a[0], b[0]),
          a[1] + reach,
        ]);
        continue;
      }
      // A diagonal is kept as a run of thin slices, each as tall as the band is there.
      const steps = Math.max(1, Math.ceil(length / 3));
      for (let i = 0; i <= steps; i++) {
        const x = a[0] + ((b[0] - a[0]) * i) / steps;
        const y = a[1] + ((b[1] - a[1]) * i) / steps;
        const r = reach * Math.SQRT2;
        taken.push([x - 1.5, y - r, x + 1.5, y + r]);
      }
    }
  }
  for (const { station } of settle) {
    taken.push([
      station.x - 8,
      station.y - station.half,
      station.x + 8,
      station.y + station.half,
    ]);
  }
  for (const { station, choices, widths } of settle) {
    const boxesOf = (label: Label): Rect[] => [
      [
        label.name[0] - (widths[0] ?? 0),
        label.name[1] - 11,
        label.name[0],
        label.name[1] + 3,
      ],
      [
        label.up[0],
        label.up[1] - 11,
        label.up[0] + (widths[1] ?? 0),
        label.up[1] + 3,
      ],
      [
        label.down[0],
        label.down[1] - 11,
        label.down[0] + (widths[2] ?? 0),
        label.down[1] + 3,
      ],
    ];
    // The name stays by its capsule: each placement first eases a little
    // further out, down or up before the next is tried. If none is clear, the
    // one that covers least wins.
    const nudges = [0, 16, 32].flatMap((dx) =>
      [0, 6, -6, 12, -12, 24, -24, 36, -36, 48, -48, 60, -60].map(
        (dy): Point => [dx, dy],
      ),
    );
    // Only what lies near this station's choices can collide with them.
    const span = choices.flatMap(boxesOf);
    const near = taken.filter((box) =>
      span.some(
        (mine) =>
          box[0] < mine[2] + 40 &&
          mine[0] - 40 < box[2] &&
          box[1] < mine[3] + 80 &&
          mine[1] - 80 < box[3],
      ),
    );
    let best = choices[0];
    let least = Infinity;
    for (const [dx, dy] of nudges) {
      for (const choice of choices) {
        const moved: Label = {
          ...choice,
          name: [choice.name[0] - dx, choice.name[1] + dy],
        };
        const covered = boxesOf(moved).reduce(
          (sum, mine) =>
            sum +
            near.reduce((area, theirs) => area + overlapArea(mine, theirs), 0),
          0,
        );
        if (covered < least) {
          least = covered;
          best = moved;
        }
        if (covered === 0) break;
      }
      if (least === 0) break;
    }
    station.label = best;
    taken.push(...boxesOf(best));
  }

  const wrongLine = termini
    .flatMap((terminus) =>
      terminus.doubts
        .filter(({ doubt }) => doubt.given !== terminus.line.label)
        .map(({ doubt }) => doubt),
    )
    .sort((a, b) => a.rank - b.rank);

  return {
    width: box.width,
    height: box.height,
    bands,
    stations,
    termini,
    rowsPerPx: 1 / rowPx,
    wrongLine,
    origin,
    terminusX,
  };
}

/** A box to keep clear: left, top, right, bottom. */
export type Rect = readonly [number, number, number, number];

/**
 * Where along a route a lens of half size `half` can rest without covering
 * anything in `avoid` or leaving `size`: the middle of the route first, then
 * further out each way. Returns the point and the index of the route point
 * just before it, so the lens can ride the route to it. With `slide` false
 * the route must run through the lens's middle. With `ink`, of the points that
 * pass, the one it scores highest wins, the middle first on a tie.
 */
export function restAlong(
  route: readonly Point[],
  half: readonly [number, number],
  avoid: readonly Rect[],
  size: readonly [number, number],
  slide = true,
  ink?: (at: Point) => number,
): { at: Point; before: number } | null {
  const lengths = legs(route).map(([a, b]) =>
    Math.hypot(b[0] - a[0], b[1] - a[1]),
  );
  const total = lengths.reduce((sum, l) => sum + l, 0);
  if (total === 0) return null;
  // Centred on the route if anywhere will do, mid-route first, then outward in
  // small steps; only then slid across it, a little before a lot.
  const fractions = [0.5];
  for (let step = 0.02; step <= 0.32; step += 0.02)
    fractions.push(0.5 - step, 0.5 + step);
  const shifts = slide ? [0, 0.25, -0.25, 0.5, -0.5] : [0];
  for (const shift of shifts.map((f) => f * half[1])) {
    const passing = fractions
      .map((fraction) => restAt(fraction, shift))
      .filter((rest) => rest !== null);
    const found =
      ink === undefined
        ? passing[0]
        : passing.reduce<(typeof passing)[number] | undefined>(
            (best, rest) =>
              best === undefined || ink(rest.at) > ink(best.at) ? rest : best,
            undefined,
          );
    if (found !== undefined) return found;
  }
  return null;

  function restAt(
    fraction: number,
    shift: number,
  ): { at: Point; before: number } | null {
    let along = fraction * total;
    let index = 0;
    while (index < lengths.length - 1 && along > (lengths[index] ?? 0)) {
      along -= lengths[index] ?? 0;
      index++;
    }
    const a = route[index];
    const b = route[index + 1];
    const length = lengths[index];
    if (a === undefined || b === undefined || length === undefined) return null;
    const f = length === 0 ? 0 : along / length;
    const on: Point = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
    const normal: Point =
      length === 0 ? [0, 1] : [-(b[1] - a[1]) / length, (b[0] - a[0]) / length];
    const at: Point = [on[0] + normal[0] * shift, on[1] + normal[1] * shift];
    const lens: Rect = [
      at[0] - half[0],
      at[1] - half[1],
      at[0] + half[0],
      at[1] + half[1],
    ];
    const inside =
      lens[0] >= 0 && lens[1] >= 0 && lens[2] <= size[0] && lens[3] <= size[1];
    return inside && avoid.every((box) => !overlaps(box, lens))
      ? { at, before: index }
      : null;
  }
}

/**
 * The place nearest `near` where the glass sits on a track, its middle within
 * a few pixels of a line, and covers no box in `avoid`.
 */
export function clearSpot(
  near: Point,
  half: readonly [number, number],
  avoid: readonly Rect[],
  tracks: readonly (readonly Point[])[],
  size: readonly [number, number],
): Point | null {
  let best: Point | null = null;
  let distance = Infinity;
  for (const track of tracks) {
    for (const [a, b] of legs(track)) {
      const steps = Math.max(
        1,
        Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 6),
      );
      for (let i = 0; i <= steps; i++) {
        const at: Point = [
          a[0] + ((b[0] - a[0]) * i) / steps,
          a[1] + ((b[1] - a[1]) * i) / steps,
        ];
        const d = Math.hypot(at[0] - near[0], at[1] - near[1]);
        if (d >= distance) continue;
        const lens: Rect = [
          at[0] - half[0],
          at[1] - half[1],
          at[0] + half[0],
          at[1] + half[1],
        ];
        const inside =
          lens[0] >= 0 &&
          lens[1] >= 0 &&
          lens[2] <= size[0] &&
          lens[3] <= size[1];
        if (inside && avoid.every((box) => !overlaps(box, lens))) {
          best = at;
          distance = d;
        }
      }
    }
  }
  return best;
}

/** Whether a glass of half size `half` at `at` stays on the map and covers no box in `avoid`. */
function clearAt(
  at: Point,
  half: readonly [number, number],
  avoid: readonly Rect[],
  size: readonly [number, number],
): boolean {
  const lens: Rect = [
    at[0] - half[0],
    at[1] - half[1],
    at[0] + half[0],
    at[1] + half[1],
  ];
  return (
    lens[0] >= 0 &&
    lens[1] >= 0 &&
    lens[2] <= size[0] &&
    lens[3] <= size[1] &&
    avoid.every((box) => !overlaps(box, lens))
  );
}

/**
 * The open place nearest `near` where the glass covers no box in `avoid` and
 * none of `bands`: each band is sampled every few pixels and kept its own half
 * width away.
 */
export function openSpot(
  near: Point,
  half: readonly [number, number],
  avoid: readonly Rect[],
  size: readonly [number, number],
  bands: readonly Band[] = [],
): Point | null {
  const blocked = [...avoid];
  for (const band of bands) {
    const pad = band.width / 2 + 4;
    for (const [a, b] of legs(band.points)) {
      const steps = Math.max(
        1,
        Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 6),
      );
      for (let i = 0; i <= steps; i++) {
        const x = a[0] + ((b[0] - a[0]) * i) / steps;
        const y = a[1] + ((b[1] - a[1]) * i) / steps;
        blocked.push([x - pad, y - pad, x + pad, y + pad]);
      }
    }
  }
  let best: Point | null = null;
  let distance = Infinity;
  for (let x = half[0]; x <= size[0] - half[0]; x += 8) {
    for (let y = half[1]; y <= size[1] - half[1]; y += 8) {
      const d = Math.hypot(x - near[0], y - near[1]);
      if (d < distance && clearAt([x, y], half, blocked, size)) {
        best = [x, y];
        distance = d;
      }
    }
  }
  return best;
}

/**
 * Where the glass rests for a row whose route has no clear stretch to centre
 * on: the clear place nearest the route's middle that still has the route
 * crossing it, at least 24 px inside its edge, else the open place nearest
 * that middle.
 */
export function restNear(
  route: readonly Point[],
  half: readonly [number, number],
  avoid: readonly Rect[],
  size: readonly [number, number],
): Point | null {
  const middle = route[Math.floor(route.length / 2)];
  if (middle === undefined) return null;
  let best: Point | null = null;
  let distance = Infinity;
  const reach: [number, number] = [half[0] - 24, half[1] - 24];
  for (const [a, b] of legs(route)) {
    const steps = Math.max(
      1,
      Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 8),
    );
    for (let i = 0; i <= steps; i++) {
      const on: Point = [
        a[0] + ((b[0] - a[0]) * i) / steps,
        a[1] + ((b[1] - a[1]) * i) / steps,
      ];
      for (let dx = -reach[0]; dx <= reach[0]; dx += 8) {
        for (let dy = -reach[1]; dy <= reach[1]; dy += 8) {
          const at: Point = [on[0] + dx, on[1] + dy];
          const d = Math.hypot(at[0] - middle[0], at[1] - middle[1]);
          if (d < distance && clearAt(at, half, avoid, size)) {
            best = at;
            distance = d;
          }
        }
      }
    }
  }
  return best ?? openSpot(middle, half, avoid, size);
}

/** Type above and below a fork's centre: a 12 px line on each side, with room. */
const TYPE_UP = 15;
const TYPE_DOWN = 17;

/**
 * Where a station's type goes. The two signs stand together in the fork, the
 * upper branch's over the lower's, where the branches have cleared them or
 * levelled off, centred in the gap between the two bands; a 45 degree band of
 * thickness t spans t * sqrt(2) vertically. The name ends just before the
 * capsule, on the side away from the track coming in.
 */
export function labelPlace(
  node: { x: number; y: number },
  rise: number,
  fall: number,
  upper: number,
  lower: number,
): Label {
  const [first] = labelChoices(node, rise, fall, upper, lower);
  return first;
}

/** Every placement a station's type may take, best first. */
export function labelChoices(
  node: { x: number; y: number },
  rise: number,
  fall: number,
  upper: number,
  lower: number,
  own = 0,
  fromAbove = false,
): [Label, ...Label[]] {
  const clearUp = TYPE_UP + upper * Math.SQRT1_2;
  const clearDown = TYPE_DOWN + lower * Math.SQRT1_2;
  const along =
    Math.min(Math.max(clearUp, clearDown), Math.max(rise, fall)) + 4;
  const top =
    node.y -
    Math.min(along, rise) +
    (along < rise ? upper * Math.SQRT1_2 : upper / 2);
  const bottom =
    node.y +
    Math.min(along, fall) -
    (along < fall ? lower * Math.SQRT1_2 : lower / 2);
  const middle = (top + bottom) / 2;
  const x = node.x + STUB + along;
  const up: Point = [x, middle - 3];
  const down: Point = [x, middle + 11];
  const before = node.x - 12;
  const over: Point = [before, node.y - own / 2 - 6];
  const under: Point = [before, node.y + own / 2 + 15];
  const [first, second] = fromAbove ? [under, over] : [over, under];
  return [
    { name: first, up, down },
    { name: second, up, down },
  ];
}

export const overlaps = (a: Rect, b: Rect): boolean =>
  a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

/** Move type clear of the glass without stacking separate readings on one edge. */
export function labelShifts(
  boxes: readonly Rect[],
  glass: Rect,
  height: number,
): number[] {
  const placed = [...boxes];
  return boxes.map((box, index) => {
    if (!overlaps(box, glass)) return 0;
    const up = glass[1] - box[3];
    const down = glass[3] - box[1];
    const candidates = Array.from({ length: 16 }, (_, step) => [
      up - step * 16,
      down + step * 16,
    ])
      .flat()
      .sort((a, b) => Math.abs(a) - Math.abs(b));
    const moved = (dy: number): Rect => [
      box[0],
      box[1] + dy,
      box[2],
      box[3] + dy,
    ];
    const dy =
      candidates.find((shift) => {
        const next = moved(shift);
        return (
          next[1] >= 16 &&
          next[3] <= height - 16 &&
          !overlaps(next, glass) &&
          placed.every((other, i) => i === index || !overlaps(next, other))
        );
      }) ?? (-up < down ? up : down);
    placed[index] = moved(dy);
    return dy;
  });
}

const overlapArea = (a: Rect, b: Rect): number =>
  Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) *
  Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));

/** The stations a row passes, origin to terminus, as the branch each one sends it down. */
export function routeOf(
  lines: readonly LeafLine[],
  row: number,
  decimals: ReadonlyMap<string, number> = new Map(),
): { stops: string[]; terminus: LeafLine } | null {
  const line = lines.find((candidate) => candidate.row_ids.includes(row));
  if (line === undefined) return null;
  const stops = line.conditions.map((condition) => {
    const split = splitOf(condition, decimals);
    const branch = goesLeft(condition) ? split.left : split.right;
    return `${split.label} ${branch} ${split.cut}`;
  });
  return { stops, terminus: line };
}
