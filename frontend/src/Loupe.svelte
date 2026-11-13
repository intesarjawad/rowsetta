<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  import type { Lens, LensShape, Stroke } from './lens';
  import type { Point, TransitMap } from './transit';

  let {
    map,
    at,
    focus = at,
    strokes,
    narrow,
    magnify,
    onmove,
    away = false,
    glass,
  }: {
    map: TransitMap;
    at: Point;
    /** The map point the glass shows, enlarged, at its middle. */
    focus?: Point;
    /** The map as the glass shows it, in map units; the bevel bends it toward the rim. */
    strokes: readonly Stroke[];
    narrow: boolean;
    /** How many times the glass enlarges the map: enough to part a band into its rows. */
    magnify: number;
    onmove: (to: Point) => void;
    /** Lifted off the map, out of sight: between drops, and with nothing to read. */
    away?: boolean;
    glass: Snippet<[TransitMap]>;
  } = $props();

  const shape = $derived<LensShape>(
    narrow
      ? { half: [92, 62], radius: 30, bevel: 16, margin: 16, magnify }
      : { half: [92, 64], radius: 30, bevel: 18, margin: 18, magnify },
  );
  const hx = $derived(shape.half[0]);
  const hy = $derived(shape.half[1]);
  const calm =
    typeof matchMedia === 'function' &&
    matchMedia('(prefers-reduced-motion: reduce)').matches;

  let canvas = $state<HTMLCanvasElement | null>(null);
  let lens = $state.raw<Lens | null>(null);

  // The glass waits until the page is readable, then loads three.
  onMount(() => {
    let disposed = false;
    let made: Lens | null = null;
    const start = setTimeout(() => {
      void import('./lens')
        .then((module) => {
          if (disposed || canvas === null) return;
          made = module.createLens(
            canvas,
            shape,
            Math.min(devicePixelRatio, narrow ? 1 : 2),
          );
          lens = made;
        })
        .catch(() => {
          lens = null;
        });
    }, 0);
    return () => {
      disposed = true;
      clearTimeout(start);
      made?.dispose();
    };
  });

  $effect(() => {
    lens?.draw(focus, magnify, strokes);
  });

  // Liquid: the glass stretches along its motion and springs back when it stops.
  let stretch = $state<Point>([1, 1]);
  let velocity: Point = [0, 0];
  let spring: Point = [0, 0];
  let wobble = 0;
  function settle(): void {
    cancelAnimationFrame(wobble);
    const step = (): void => {
      const target: Point = [
        Math.min(Math.abs(velocity[0]) * 0.006, 0.14),
        Math.min(Math.abs(velocity[1]) * 0.006, 0.14),
      ];
      velocity = [velocity[0] * 0.82, velocity[1] * 0.82];
      spring = [
        spring[0] + (target[0] - (stretch[0] - 1)) * 0.22,
        spring[1] + (target[1] - (stretch[1] - 1)) * 0.22,
      ];
      spring = [spring[0] * 0.72, spring[1] * 0.72];
      stretch = [
        stretch[0] + spring[0] - spring[1] * 0.45,
        stretch[1] + spring[1] - spring[0] * 0.45,
      ];
      const moving =
        Math.abs(stretch[0] - 1) + Math.abs(stretch[1] - 1) > 0.002 ||
        Math.abs(velocity[0]) + Math.abs(velocity[1]) > 0.2;
      if (moving && !document.hidden) wobble = requestAnimationFrame(step);
      else stretch = [1, 1];
    };
    wobble = requestAnimationFrame(step);
  }

  let grab: { id: number; from: Point; centre: Point; last: Point } | null =
    null;
  function down(event: PointerEvent): void {
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    grab = {
      id: event.pointerId,
      from: [event.clientX, event.clientY],
      centre: at,
      last: [event.clientX, event.clientY],
    };
  }
  function move(event: PointerEvent): void {
    if (grab?.id !== event.pointerId) return;
    const to: Point = [
      Math.max(
        0,
        Math.min(map.width, grab.centre[0] + event.clientX - grab.from[0]),
      ),
      Math.max(
        0,
        Math.min(map.height, grab.centre[1] + event.clientY - grab.from[1]),
      ),
    ];
    if (!calm) {
      velocity = [event.clientX - grab.last[0], event.clientY - grab.last[1]];
      settle();
    }
    grab.last = [event.clientX, event.clientY];
    onmove(to);
  }
  function up(event: PointerEvent): void {
    if (grab?.id === event.pointerId) grab = null;
  }
</script>

<div
  class="loupe"
  class:away
  style:transform={`translate(${String(at[0] - hx)}px, ${String(at[1] - hy)}px)`}
  style:width={`${String(hx * 2)}px`}
  style:height={`${String(hy * 2)}px`}
>
  <div
    class="body"
    style:transform={`scale(${String(stretch[0])}, ${String(stretch[1])})`}
  >
    <div
      class="window"
      class:ring={lens === null}
      style:border-radius={`${String(shape.radius)}px`}
      aria-hidden="true"
    >
      <svg
        width={map.width}
        height={map.height}
        viewBox={`0 0 ${String(map.width)} ${String(map.height)}`}
        style:transform={`translate(${String(hx - focus[0] * shape.magnify)}px, ${String(hy - focus[1] * shape.magnify)}px) scale(${String(shape.magnify)})`}
      >
        {@render glass(map)}
      </svg>
    </div>
    <canvas
      bind:this={canvas}
      class="glass"
      class:ready={lens !== null}
      style:left={`${String(-shape.margin)}px`}
      style:top={`${String(-shape.margin)}px`}
      style:width={`${String(hx * 2 + shape.margin * 2)}px`}
      style:height={`${String(hy * 2 + shape.margin * 2)}px`}
      aria-hidden="true"
    ></canvas>
    <div
      class="handle"
      style:border-radius={`${String(shape.radius)}px`}
      onpointerdown={down}
      onpointermove={move}
      onpointerup={up}
      onpointercancel={up}
      aria-hidden="true"
    ></div>
  </div>
</div>

<style>
  .loupe {
    position: absolute;
    left: 0;
    top: 0;
    z-index: 2;
    pointer-events: none;
  }
  .body {
    position: relative;
    transition:
      opacity 90ms ease,
      scale 90ms ease;
    width: 100%;
    height: 100%;
  }
  .away .body {
    opacity: 0;
    scale: 1.06;
  }
  .away .handle {
    pointer-events: none;
  }
  .window {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: #ffffff;
  }
  .window svg {
    position: absolute;
    left: 0;
    top: 0;
    transform-origin: 0 0;
    display: block;
  }
  /* Until the glass is ready, and without WebGL, an ink ring stands in for it. */
  .window.ring {
    box-shadow: inset 0 0 0 2px var(--ink);
  }
  .glass {
    position: absolute;
    opacity: 0;
    transition: opacity 240ms ease;
  }
  .glass.ready {
    opacity: 1;
  }
  .handle {
    position: absolute;
    inset: 0;
    pointer-events: auto;
    cursor: grab;
    touch-action: none;
  }
  .handle:active {
    cursor: grabbing;
  }
</style>
