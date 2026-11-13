<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Drawn, Ghost } from './interchange';
  import type { Point } from './transit';
  import { fade } from 'svelte/transition';
  import { lineColour } from './palette';
  import SvgLabel from './SvgLabel.svelte';
  import { typeLines, type Station, type TransitMap } from './transit';
  let {
    m,
    id,
    bands,
    trails,
    dyes,
    fixing,
    receiving,
    ghosts,
    reveal,
    trunk,
    narrow,
    phone,
    ink,
    selectedRow,
    fixedCount,
    rowCount,
    classes,
    calm,
    font,
    LIFT_MS,
    LAY_MS,
    GHOST_FOLD_MS,
    foldAt,
    nudge,
    roundel,
  }: {
    m: TransitMap;
    id: string;
    bands: Drawn[];
    trails: { key: string; d: string; colour: string }[];
    dyes: {
      key: string;
      row: number;
      d: string;
      colour: string;
      delay: number;
      duration: number;
    }[];
    fixing: ReadonlySet<number>;
    receiving: ReadonlySet<string>;
    ghosts: Ghost[];
    reveal: number;
    trunk: number;
    narrow: boolean;
    phone: boolean;
    ink: number;
    selectedRow: number | null;
    fixedCount: number;
    rowCount: number | null;
    classes: readonly string[];
    calm: boolean;
    font: string;
    LIFT_MS: number;
    LAY_MS: number;
    GHOST_FOLD_MS: number;
    foldAt: (ghost: Ghost) => number;
    nudge: (station: Station, line: number) => string | undefined;
    roundel: Snippet<[number, number, string | null, number?]>;
  } = $props();
  const quiet = $derived(fixing.size > 0);
  const path = (points: readonly Point[]): string =>
    points
      .map(
        (p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(2)} ${p[1].toFixed(2)}`,
      )
      .join('');
</script>

<defs>
  <clipPath {id}>
    <rect x="0" y="0" width={m.width * reveal} height={m.height} />
  </clipPath>
</defs>
<g class="tracks" font-family={font}>
  <g clip-path={reveal < 1 ? `url(#${id})` : undefined}>
    {#each bands as band (band.key)}
      {@const moving = band.row !== null && fixing.has(band.row)}
      {@const width = moving ? Math.max(band.width, 6) : band.width}
      {@const opacity = band.opacity * (quiet && !moving ? 0.22 : 1)}
      {#if band.casing || moving}
        <path
          d={path(band.points)}
          fill="none"
          stroke="#0d0d0d"
          stroke-width={width + 2.4}
          stroke-linejoin="miter"
          {opacity}
        />
      {/if}
      <path
        d={path(band.points)}
        fill="none"
        stroke={band.colour}
        stroke-width={width}
        stroke-linejoin="miter"
        {opacity}
      />
    {/each}
    {#each trails as trail (trail.key)}
      <path
        d={trail.d}
        fill="none"
        stroke="#0d0d0d"
        stroke-width="8.4"
        stroke-linejoin="miter"
      />
      <path
        d={trail.d}
        fill="none"
        stroke={trail.colour}
        stroke-width="6"
        stroke-linejoin="miter"
      />
    {/each}
    {#each dyes as dye (dye.key)}
      <path
        class="dye"
        d={dye.d}
        fill="none"
        stroke="#ffffff"
        stroke-width="10"
        pathLength="1"
        style:animation-delay={`${String(dye.delay)}ms`}
        style:animation-duration={`${String(dye.duration)}ms`}
      />
      <path
        class="dye"
        d={dye.d}
        fill="none"
        stroke={dye.colour}
        stroke-width="6"
        pathLength="1"
        style:animation-delay={`${String(dye.delay)}ms`}
        style:animation-duration={`${String(dye.duration)}ms`}
      />
    {/each}
    <g>
      {#if !narrow}
        <text
          class="halo"
          x={m.origin[0]}
          y={m.origin[1] - trunk / 2 - 10}
          font-size="12"
          font-weight="700"
          fill={quiet ? '#8a8d92' : '#0d0d0d'}>{rowCount ?? ''} rows</text
        >
      {/if}
      {#each m.stations as station (station.key)}
        {@const shade = quiet ? '#8a8d92' : '#0d0d0d'}
        <g
          in:fade={{
            duration: calm ? 0 : 240,
            delay: calm ? 0 : LIFT_MS + (station.x / m.width) * LAY_MS * 0.6,
          }}
        >
          <rect
            x={station.x - 7}
            y={station.y - station.half}
            width="14"
            height={station.half * 2}
            rx="7"
            fill="#ffffff"
            stroke={shade}
            stroke-width="2.5"
          />
          {#if !narrow}
            {@const [, upper, lower] = typeLines(station.split, station.upLeft)}
            <SvgLabel
              text={`${station.split.label} ${station.split.cut}`}
              maxWidth={Math.max(0, station.label.name[0] - 8)}
              class="halo"
              style={`transform: ${nudge(station, 0) ?? 'none'}`}
              x={station.label.name[0]}
              y={station.label.name[1]}
              text-anchor="end"
              font-size="12"
              font-weight="700"
              fill={shade}
            />
            <SvgLabel
              text={upper}
              maxWidth={Math.max(0, m.width - station.label.up[0] - 8)}
              class="halo"
              style={`transform: ${nudge(station, 1) ?? 'none'}`}
              x={station.label.up[0]}
              y={station.label.up[1]}
              font-size={14}
              font-weight="700"
              fill={shade}
            />
            <SvgLabel
              text={lower}
              maxWidth={Math.max(0, m.width - station.label.down[0] - 8)}
              class="halo"
              style={`transform: ${nudge(station, 2) ?? 'none'}`}
              x={station.label.down[0]}
              y={station.label.down[1]}
              font-size={14}
              font-weight="700"
              fill={shade}
            />
          {/if}
        </g>
      {/each}
      {#each m.termini as terminus (terminus.key)}
        {@const answer = terminus.line.label}
        {@const ghost = ghosts.find((g) => g.key === terminus.key)}
        <g
          opacity={quiet && !receiving.has(terminus.key) ? 0.35 : 1}
          class:ghost={ghost !== undefined}
          style:--fold={ghost === undefined
            ? undefined
            : `${String(ghost.toY)}px`}
          style:animation-delay={ghost === undefined
            ? undefined
            : `${String(foldAt(ghost))}ms`}
          style:animation-duration={`${String(GHOST_FOLD_MS)}ms`}
          in:fade={{
            duration: calm ? 0 : 260,
            delay: calm ? 0 : LIFT_MS + LAY_MS * 0.55,
          }}
          out:fade={{ duration: calm ? 0 : LIFT_MS }}
        >
          <rect
            x={terminus.x}
            y={terminus.y - terminus.half}
            width="6"
            height={terminus.half * 2}
            fill="#0d0d0d"
          />
          {@render roundel(terminus.x + 20 * ink, terminus.y, answer, ink)}
          {#if !narrow}
            <SvgLabel
              text={answer ?? 'No answer'}
              maxWidth={Math.max(0, m.width - terminus.x - 44)}
              x={terminus.x + 36}
              y={terminus.y - 1}
              font-size="14"
              font-weight="700"
              fill="#0d0d0d"
              text-decoration={ghost === undefined ? undefined : 'line-through'}
            />
            {@const counts = ghost
              ? `merges into ${ghost.into.label ?? 'no answer'}, ${String(ghost.into.row_ids.length)} rows`
              : `${String(terminus.line.row_ids.length)} rows${terminus.counts
                  .filter(([cls]) => cls !== answer)
                  .map(([cls, n]) => `, ${String(n)} ${cls}`)
                  .join('')}`}
            {#key counts}
              <SvgLabel
                text={counts}
                maxWidth={Math.max(0, m.width - terminus.x - 44)}
                class={fixedCount > 0 ? 'tick' : undefined}
                style={`--flash: ${
                  answer === null ? '#0d0d0d' : lineColour(classes, answer)
                }`}
                x={terminus.x + 36}
                y={terminus.y + 13}
                font-size="11.5"
                fill="#4f5257"
              />
            {/key}
          {/if}
        </g>
      {/each}
    </g>
    {#each m.termini as terminus (terminus.key)}
      {#each terminus.doubts as end, index (end.doubt.row)}
        {@const r = 7.5 * ink}
        {@const x = phone
          ? terminus.x - 6 * ink - r - index * 18 * ink
          : terminus.x - 24 - r}
        {@const y = phone
          ? terminus.y
          : terminus.y + (index - (terminus.doubts.length - 1) / 2) * 18}
        <g opacity={quiet && !fixing.has(end.doubt.row) ? 0.35 : 1}>
          {#if !phone}
            <polyline
              points={`${String(x)},${String(y)} ${String(x + r + 6)},${String(end.y)} ${String(terminus.x - 5)},${String(end.y)}`}
              fill="none"
              stroke="#0d0d0d"
              stroke-width="1.5"
            />
          {/if}
          <circle
            cx={x}
            cy={y}
            {r}
            fill={selectedRow === end.doubt.row ? '#ffffff' : '#0d0d0d'}
            stroke={selectedRow === end.doubt.row ? '#0d0d0d' : '#ffffff'}
            stroke-width={2 * ink}
          />
          {#if !narrow || phone}
            <text
              {x}
              y={y + 3.5 * ink}
              text-anchor="middle"
              font-size={10 * ink}
              font-weight="700"
              fill={selectedRow === end.doubt.row ? '#0d0d0d' : '#ffffff'}
              >{end.doubt.rank}</text
            >
          {/if}
        </g>
      {/each}
    {/each}
  </g>
</g>

<style>
  @media (prefers-reduced-motion: reduce) {
    .tracks :global(.halo) {
      transition: none;
    }
  }
  .tracks :global(.tick) {
    animation: tick 900ms var(--ease-out);
  }
  @keyframes tick {
    from {
      fill: var(--flash);
      transform: translateY(-5px);
      opacity: 0;
    }
    20% {
      fill: var(--flash);
      transform: none;
      opacity: 1;
    }
  }
  .ghost {
    animation-name: fold;
    animation-timing-function: cubic-bezier(0.5, 0, 0.2, 1);
    animation-fill-mode: forwards;
  }
  .tracks :global(.halo) {
    paint-order: stroke;
    stroke: #ffffff;
    stroke-width: 4px;
    stroke-linejoin: round;
    transition: transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .dye {
    stroke-dasharray: 1 1;
    stroke-dashoffset: 1;
    animation: dye 900ms linear forwards;
  }
  @keyframes dye {
    to {
      stroke-dashoffset: 0;
    }
  }
</style>
