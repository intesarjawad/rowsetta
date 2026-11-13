import { onDestroy, untrack } from 'svelte';
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import type { ByRow } from './backend/types';
import type { Drawn } from './interchange';
import type { Stroke } from './lens';
import { bandColour, lineColour } from './palette';
import {
  legs,
  offsetLine,
  restNear,
  restAlong,
  nearestOn,
  labelShifts,
  typeLines,
  typeWidth,
  type Rect,
  type Doubt,
  type Point,
  type Station,
  type TransitMap,
} from './transit';

export const DYE_MS = 900;
export const MORPH_MS = 760;
export const LIFT_MS = 220;
export const LAY_MS = 1100;
export const GHOST_FOLD_MS = 520;
const GHOST_HOLD_MS = 2000;
const GHOST_STEP_MS = 320;
export const foldAt = (ghost: { order: number }): number =>
  GHOST_HOLD_MS + ghost.order * GHOST_STEP_MS;
const SIGN_SIZE = 14;
// Must match Loupe.svelte's bevel.
const BEVEL = 18;
const RIDE_MS = 1300;

interface MotionSource {
  map: TransitMap | null;
  classes: readonly string[];
  human: ByRow<string>;
  selectedRow: number | null;
  narrow: boolean;
}

export function createInterchangeMotion(
  source: () => MotionSource,
  calm: boolean,
) {
  const map = $derived(source().map);
  const classes = $derived(source().classes);
  const drawnHuman = $derived(source().human);
  const selectedRow = $derived(source().selectedRow);
  const narrow = $derived(source().narrow);
  function drawnOf(next: TransitMap): Drawn[] {
    return next.bands.map((band) => ({
      key: band.key,
      points: band.points.map((p): Point => [p[0], p[1]]),
      width: band.width,
      colour: bandColour(classes, band.cls, band.kind),
      casing: band.doubt !== null,
      row: band.doubt?.row ?? null,
      rows: band.rows,
      opacity: 1,
    }));
  }

  let fixing = $state.raw<ReadonlySet<number>>(new SvelteSet());
  let bands = $state.raw<Drawn[]>([]);
  let reveal = $state(1);
  let frame = 0;
  let laidAt = '';
  const dyed: Partial<Record<number, string>> = {};
  let trails = $state.raw<{ key: string; d: string; colour: string }[]>([]);
  let dyes = $state.raw<
    {
      key: string;
      row: number;
      d: string;
      colour: string;
      width: number;
      delay: number;
      duration: number;
    }[]
  >([]);

  const ease = (t: number): number =>
    t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;

  const same = (a: readonly Drawn[], b: readonly Drawn[]): boolean =>
    a.length === b.length &&
    a.every((band, i) => {
      const other = b[i];
      return (
        other !== undefined &&
        band.key === other.key &&
        band.width === other.width &&
        band.colour === other.colour &&
        band.points.every((p, j) => {
          const q = other.points[j];
          return q !== undefined && p[0] === q[0] && p[1] === q[1];
        })
      );
    });

  const shape = (drawn: readonly Drawn[]): string =>
    [
      ...new SvelteSet(
        drawn.map((band) => band.key.slice(0, band.key.indexOf('|'))),
      ),
    ]
      .sort()
      .join();

  function relay(next: Drawn[]): void {
    const from = bands;
    const start = performance.now();
    const step = (now: number): void => {
      const t = (now - start) / LIFT_MS;
      if (t < 1) {
        bands = from.map((band) => ({ ...band, opacity: 1 - t }));
        frame = requestAnimationFrame(step);
        return;
      }
      bands = next;
      const u = Math.min((now - start - LIFT_MS) / LAY_MS, 1);
      reveal = 1 - (1 - u) ** 3;
      if (u < 1) frame = requestAnimationFrame(step);
    };
    reveal = 0;
    frame = requestAnimationFrame(step);
  }

  function morph(next: Drawn[], size: string): void {
    if (same(bands, next)) return;
    cancelAnimationFrame(frame);
    reveal = 1;
    const from = bands;
    if (from.length === 0 || calm || size !== laidAt) {
      laidAt = size;
      bands = next;
      return;
    }
    if (shape(from) !== shape(next)) {
      relay(next);
      return;
    }
    const before = new SvelteMap(from.map((band) => [band.key, band]));
    const keys = new SvelteSet(next.map((band) => band.key));
    const pairs: { a: Drawn; b: Drawn; fold: boolean; keep?: boolean }[] = [];
    for (const a of from) {
      if (keys.has(a.key)) continue;
      const colour = (a.row !== null ? dyed[a.row] : undefined) ?? a.colour;
      const into =
        a.row !== null
          ? next.find(
              (band) =>
                band.key ===
                `${a.key.slice(0, a.key.lastIndexOf('|'))}|human:${drawnHuman[String(a.row)] ?? ''}`,
            )
          : undefined;
      const b =
        into !== undefined && into.points.length === a.points.length
          ? {
              ...into,
              key: a.key,
              width: a.width,
              rows: a.rows,
              colour,
              casing: false,
            }
          : { ...a, opacity: 0 };
      const keep = false;
      pairs.push({ a: { ...a, colour }, b, fold: true, keep });
    }
    for (const b of next) {
      const a = before.get(b.key);
      pairs.push({
        a:
          a !== undefined && a.points.length === b.points.length
            ? a
            : { ...b, opacity: 0 },
        b,
        fold: false,
      });
    }
    const start = performance.now();
    const step = (now: number): void => {
      const t = Math.min((now - start) / MORPH_MS, 1);
      const e = ease(t);
      bands = pairs.map(({ a, b, fold, keep }) => ({
        key: b.key,
        points: a.points.map((p, i): Point => [
          p[0] + ((b.points[i]?.[0] ?? p[0]) - p[0]) * e,
          p[1] + ((b.points[i]?.[1] ?? p[1]) - p[1]) * e,
        ]),
        width: a.width + (b.width - a.width) * e,
        colour: keep === true ? b.colour : e < 0.5 ? a.colour : b.colour,
        casing: fold ? a.casing && t < 0.25 : b.casing,
        rows: b.rows,
        row: fold ? a.row : b.row,
        opacity:
          keep === true
            ? 1
            : fold
              ? 1 - Math.max(0, (t - 0.75) / 0.25)
              : a.opacity + (b.opacity - a.opacity) * e,
      }));
      if (t < 1) {
        frame = requestAnimationFrame(step);
      } else {
        bands = next;
        // Only the threads this fold carried; a later drop may already be dyed.
        for (const { a, fold } of pairs) {
          if (fold && a.row !== null) dyed[a.row] = undefined;
        }
        trails = [
          ...trails,
          ...pairs
            .filter((pair) => pair.keep === true)
            .map(({ a, b }) => ({
              key: a.key,
              d: path(b.points),
              colour: b.colour,
            })),
        ];
      }
    };
    frame = requestAnimationFrame(step);
  }

  $effect(() => {
    if (map === null) return;
    const next = drawnOf(map);
    const size = `${String(map.width)}x${String(map.height)}`;
    untrack(() => {
      morph(next, size);
    });
  });

  const path = (points: readonly Point[]): string =>
    points
      .map(
        (p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(2)} ${p[1].toFixed(2)}`,
      )
      .join('');

  const PITCH = 2.4;
  const magnify = $derived(
    map === null ? 4 : Math.min(12, Math.max(3, PITCH * map.rowsPerPx)),
  );

  function hairlines(band: Drawn): string {
    const n = band.rows;
    if (n <= 1) return path(band.points);
    const spacing = band.width / n;
    let d = '';
    for (let k = 0; k < n; k++) {
      d += path(offsetLine(band.points, (k + 0.5 - n / 2) * spacing));
    }
    return d;
  }

  const lifted = $derived(
    new SvelteSet([...fixing, ...(selectedRow === null ? [] : [selectedRow])]),
  );

  function routeOfRow(row: number): Point[] {
    return bands
      .filter((band) => band.row === row)
      .sort(byRoute)
      .flatMap((band) => band.points);
  }

  function threadPath(row: number): string {
    return path(routeOfRow(row));
  }

  let anchored: { lens: Point; at: Point } | null = null;
  const focus = $derived.by((): Point => {
    for (const row of lifted) {
      const near = nearestOn(routeOfRow(row), lens);
      if (
        near !== null &&
        Math.abs(near.at[0] - lens[0]) < half[0] &&
        Math.abs(near.at[1] - lens[1]) < half[1]
      ) {
        anchored = { lens, at: near.at };
        return near.at;
      }
    }
    // A glass left where a fix dropped its row keeps the same picture.
    if (anchored?.lens === lens) return anchored.at;
    anchored = null;
    return lens;
  });

  const glassStrokes = $derived.by((): (Stroke & { key: string })[] => {
    const px = 1 / magnify;
    const parted = map !== null && magnify / map.rowsPerPx >= 1.5;
    const out: (Stroke & { key: string })[] = [];
    for (const band of bands) {
      if (band.row !== null && lifted.has(band.row)) continue;
      const rows = band.row === null && parted;
      out.push({
        key: band.key,
        d: rows ? hairlines(band) : path(band.points),
        colour: band.colour,
        width: rows
          ? Math.max((band.width / Math.max(band.rows, 1)) * 0.7, px)
          : band.row === null
            ? band.width
            : px * 2.5,
        opacity: band.opacity,
      });
    }
    for (const row of lifted) {
      const band = bands.find((b) => b.row === row);
      if (band === undefined) continue;
      const d = threadPath(row);
      out.push(
        {
          key: `lift-casing-${String(row)}`,
          d,
          colour: '#0d0d0d',
          width: px * 7,
          opacity: band.opacity,
        },
        {
          key: `lift-${String(row)}`,
          d,
          colour: band.colour,
          width: px * 4,
          opacity: band.opacity,
        },
      );
    }
    return out;
  });

  const trunk = $derived(
    bands
      .filter((band) => band.key.startsWith('in|'))
      .reduce((sum, band) => sum + band.width + 1.5, 0),
  );

  const byRoute = (a: { key: string }, b: { key: string }): number => {
    const depth = (band: { key: string }): number => {
      const edge = band.key.slice(0, band.key.indexOf('|'));
      return edge === 'in' ? -1 : edge.length;
    };
    return depth(a) - depth(b);
  };

  const length = (points: readonly Point[]): number =>
    legs(points).reduce(
      (sum, [a, b]) => sum + Math.hypot(b[0] - a[0], b[1] - a[1]),
      0,
    );

  const half = $derived<[number, number]>(narrow ? [92, 62] : [92, 64]);

  const solid = $derived.by((): Rect[] => {
    if (map === null) return [];
    return [
      [map.terminusX - 48, 0, map.width, map.height],
      [0, map.height - 80, map.origin[0] + 350, map.height],
      // The origin's count and trunk; the open sky above them is fair ground.
      [0, map.origin[1] - 100, map.origin[0] + 80, map.height],
      ...map.stations.map((station): Rect => [
        station.x - 12,
        station.y - station.half - 6,
        station.x + 12,
        station.y + station.half + 6,
      ]),
    ];
  });

  function typeBoxes(station: Station): [Rect, Rect, Rect] {
    const [name, upper, lower] = typeLines(station.split, station.upLeft);
    const { label } = station;
    return [
      [
        label.name[0] - typeWidth(name) - 4,
        label.name[1] - 14,
        label.name[0] + 4,
        label.name[1] + 4,
      ],
      [
        label.up[0] - 4,
        label.up[1] - SIGN_SIZE,
        label.up[0] + typeWidth(upper),
        label.up[1] + 4,
      ],
      [
        label.down[0] - 4,
        label.down[1] - SIGN_SIZE,
        label.down[0] + typeWidth(lower),
        label.down[1] + 4,
      ],
    ];
  }

  const keepClear = $derived.by((): Rect[] =>
    map === null || narrow
      ? solid
      : [...solid, ...map.stations.flatMap((station) => typeBoxes(station))],
  );

  const shoved = $derived.by((): Record<string, number> => {
    const moves: Record<string, number> = {};
    if (map === null || narrow || !parked || idle) return moves;
    const top = lens[1] - half[1] - 4;
    const bottom = lens[1] + half[1] + 4;
    const glass: Rect = [
      lens[0] - half[0] - 4,
      top,
      lens[0] + half[0] + 4,
      bottom,
    ];
    const units = map.stations.flatMap((station) => {
      const [name, upper, lower] = typeBoxes(station);
      return [
        { station, lines: [0], box: name },
        {
          station,
          lines: [1, 2],
          box: [
            Math.min(upper[0], lower[0]),
            upper[1],
            Math.max(upper[2], lower[2]),
            lower[3],
          ] as Rect,
        },
      ];
    });
    const shifts = labelShifts(
      units.map((unit) => unit.box),
      glass,
      map.height,
    );
    for (const [index, unit] of units.entries()) {
      const dy = shifts[index] ?? 0;
      if (dy === 0) continue;
      for (const line of unit.lines)
        moves[`${unit.station.key}:${String(line)}`] = dy;
    }
    return moves;
  });

  const nudge = (station: Station, line: number): string | undefined => {
    const dy = shoved[`${station.key}:${String(line)}`];
    return dy === undefined ? undefined : `translateY(${String(dy)}px)`;
  };

  const inkDots = $derived.by((): [number, number, number][] => {
    const dots: [number, number, number][] = [];
    for (const [index, band] of (map?.bands ?? []).entries()) {
      for (const [a, b] of legs(band.points)) {
        const n = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 6);
        for (let i = 0; i < n; i++) {
          const f = i / n;
          dots.push([
            a[0] + (b[0] - a[0]) * f,
            a[1] + (b[1] - a[1]) * f,
            index,
          ]);
        }
      }
    }
    return dots;
  });

  const inkUnder = (at: Point): number =>
    new SvelteSet(
      inkDots
        .filter(
          ([x, y]) =>
            Math.abs(x - at[0]) < half[0] - BEVEL &&
            Math.abs(y - at[1]) < half[1] - BEVEL,
        )
        .map(([, , band]) => band),
    ).size;

  function restOn(row: number): { at: Point; through: Point[] } | null {
    if (map === null) return null;
    // The map as laid out, not as drawn: the drawing may still be mid-tween.
    const route = map.bands
      .filter((band) => band.doubt?.row === row)
      .sort(byRoute)
      .flatMap((band) => band.points);
    if (route.length < 2) return null;
    const size = [map.width, map.height] as const;
    // On the thread clear of everything, else on the thread clear of the
    // interchanges with their type moved aside, and only then beside it.
    const rest =
      restAlong(route, half, keepClear, size, false, inkUnder) ??
      restAlong(route, half, solid, size, false, inkUnder) ??
      restAlong(route, half, keepClear, size);
    if (rest !== null) {
      return { at: rest.at, through: route.slice(0, rest.before + 1) };
    }
    const at = restNear(route, half, keepClear, size);
    return at === null ? null : { at, through: [] };
  }

  function dye(doubt: Doubt, ms: number): void {
    const colour = lineColour(classes, doubt.likely);
    const thread = bands.filter((band) => band.row === doubt.row).sort(byRoute);
    const total =
      thread.reduce((sum, band) => sum + length(band.points), 0) || 1;
    let run = 0;
    dyes = [
      ...dyes,
      ...thread.map((band) => {
        const stretch = length(band.points);
        const step = {
          key: band.key,
          row: doubt.row,
          d: path(band.points),
          colour,
          width: band.width,
          delay: (run / total) * ms,
          duration: (stretch / total) * ms,
        };
        run += stretch;
        return step;
      }),
    ];
    dyed[doubt.row] = colour;
  }

  let idle = $state(false);

  // Keep the terminus name in view beside the glass's right edge.
  let lens = $state<Point>([0, 0]);
  let parked = $state(false);
  const travelling = false;
  const reach = $derived(narrow ? 24 - 92 : 34 - 92);
  let ride = 0;
  onDestroy(() => {
    if (typeof cancelAnimationFrame === 'function') {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(ride);
    }
  });

  function glide(
    to: Point,
    through: readonly Point[] = [],
    duration = through.length > 0 ? RIDE_MS : 320,
  ): void {
    cancelAnimationFrame(ride);
    parked = false;
    const route = legs([lens, ...through, to]).map(([a, b]) => ({
      a,
      b,
      length: Math.hypot(b[0] - a[0], b[1] - a[1]),
    }));
    const last = route.at(-1);
    const total = route.reduce((sum, leg) => sum + leg.length, 0);
    if (calm || total < 1 || last === undefined) {
      lens = to;
      parked = true;
      return;
    }
    const start = performance.now();
    const step = (now: number): void => {
      const t = Math.min((now - start) / duration, 1);
      let along = ease(t) * total;
      let leg = last;
      let f = 1;
      for (const next of route) {
        if (along <= next.length) {
          leg = next;
          f = next.length === 0 ? 1 : along / next.length;
          break;
        }
        along -= next.length;
      }
      const { a, b } = leg;
      lens = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
      if (t < 1) ride = requestAnimationFrame(step);
      else parked = true;
    };
    ride = requestAnimationFrame(step);
  }

  function moved(to: Point): void {
    idle = false;
    parked = false;
    cancelAnimationFrame(ride);
    lens = to;
  }

  return {
    get fixing() {
      return fixing;
    },
    set fixing(value: typeof fixing) {
      fixing = value;
    },
    get bands() {
      return bands;
    },
    get reveal() {
      return reveal;
    },
    get trails() {
      return trails;
    },
    set trails(value: typeof trails) {
      trails = value;
    },
    get dyes() {
      return dyes;
    },
    set dyes(value: typeof dyes) {
      dyes = value;
    },
    get lens() {
      return lens;
    },
    set lens(value: typeof lens) {
      lens = value;
    },
    get parked() {
      return parked;
    },
    get idle() {
      return idle;
    },
    set idle(value: typeof idle) {
      idle = value;
    },
    get travelling() {
      return travelling;
    },
    get focus() {
      return focus;
    },
    get glassStrokes() {
      return glassStrokes;
    },
    get trunk() {
      return trunk;
    },
    get magnify() {
      return magnify;
    },
    get reach() {
      return reach;
    },
    get lifted() {
      return lifted;
    },
    routeOfRow,
    restOn,
    glide,
    nudge,
    dye,
    moved,
  };
}
