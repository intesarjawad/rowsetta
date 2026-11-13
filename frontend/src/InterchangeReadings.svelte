<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Cell, Distilled } from './backend/types';
  import type { ShownSuspect } from './audit';
  import type { WholeTable } from './rows';
  import type { Studio } from './state.svelte';
  import { columnWords, routeOf, type Doubt } from './transit';
  import { lineColour } from './palette';
  import SvgLabel from './SvgLabel.svelte';
  let {
    studio,
    table,
    rule,
    classes,
    listed,
    thin,
    sparse,
    doubts,
    phone,
    onread,
    onfix,
    onidle,
    bullet,
    roundel,
  }: {
    studio: Studio;
    table: WholeTable | null;
    rule: Distilled | null;
    classes: readonly string[];
    listed: ShownSuspect[];
    thin: ShownSuspect[];
    sparse: ReadonlyMap<number, string>;
    doubts: Doubt[];
    phone: boolean;
    onread: (doubt: Doubt) => void;
    onfix: (doubt: Doubt) => Promise<void>;
    onidle: () => void;
    bullet: Snippet<[string]>;
    roundel: Snippet<[number, number, string | null, number?]>;
  } = $props();
  const human = $derived(studio.workspace?.human ?? {});
  const workspace = $derived(studio.workspace);
  const FONT = "Ronzino, 'Helvetica Neue', Arial, sans-serif";
  const percent = (p: number): string =>
    p < 0.001 ? '<0.1%' : `${(p * 100).toFixed(1)}%`;

  function values(row: number): [string, string][] {
    const record = table?.rows.get(row);
    if (record === undefined) return [];
    const show = (cell: Cell | undefined): string =>
      cell === null || cell === undefined ? 'missing' : String(cell);
    return (table?.columns ?? [])
      .filter((column) => column.name !== workspace?.target)
      .map((column) => {
        const [name, unit] = columnWords(column.name);
        const cell = record[column.name];
        return [
          name,
          unit === undefined || cell === null || cell === undefined
            ? show(cell)
            : `${show(cell)} ${unit}`,
        ];
      });
  }
</script>

{#snippet arrow()}<svg class="arrow" viewBox="0 0 14 10" aria-hidden="true"
    ><path d="M0 5h12M8 1l4 4-4 4" /></svg
  ><span class="visually-hidden">&nbsp;to&nbsp;</span>{/snippet}
{#if studio.suspects !== null}
  <ol class="doubts" aria-label="Labels the model doubts most">
    {#each listed as item (item.suspect.row_id)}
      {@const s = item.suspect}
      {@const doubt = doubts.find((d) => d.row === s.row_id)}
      {@const route =
        phone && rule !== null
          ? routeOf(rule.leaf_summary, s.row_id, studio.ruleDecimals)
          : null}
      <li
        class="doubt"
        class:quiet={item.state !== 'open'}
        class:on={studio.selectedRow === s.row_id}
      >
        <button
          type="button"
          aria-expanded={studio.selectedRow === s.row_id}
          disabled={doubt === undefined}
          onclick={() => {
            if (doubt === undefined) return;
            if (studio.selectedRow === s.row_id) {
              studio.selectedRow = null;
              onidle();
            } else onread(doubt);
          }}
        >
          <span class="roundel" aria-hidden="true">{item.rank + 1}</span>
          <span class="row">Row {s.row_id}</span>
          {#if item.state === 'fixed'}
            {@const now = human[String(s.row_id)]}
            <span class="what"
              >now {#if now !== undefined}{@render bullet(now)}{/if}{now ??
                'unlabelled'}</span
            >
          {:else if item.state === 'stet'}
            <span class="what">{s.given} kept</span>
          {:else}
            <span class="what"
              >{@render bullet(s.given)}<span class="given">{s.given}</span
              >{@render arrow()}<span>{s.likely}</span></span
            >
          {/if}
          <span class="pct">{percent(s.given_probability)}</span>
        </button>
        {#if route !== null}
          {@const n = route.stops.length}
          {@const xs = route.stops.map(
            (_, i) => 10 + (n > 1 ? (i * 290) / (n - 1) : 0),
          )}
          <svg
            class="strip"
            viewBox="0 0 358 60"
            role="img"
            aria-label={`Row ${String(s.row_id)} rides: ${route.stops.join(', ')}, to ${route.terminus.label ?? 'no answer'}.`}
          >
            <rect
              x="0"
              y="27.5"
              width="320"
              height="5"
              fill={lineColour(classes, s.given)}
            />
            {#each route.stops as stop, i (i)}
              <circle
                cx={xs[i]}
                cy="30"
                r="5"
                fill="#ffffff"
                stroke="#0d0d0d"
                stroke-width="2"
              />
              <SvgLabel
                text={stop}
                maxWidth={n > 1 ? 290 / (n - 1) : 290}
                x={xs[i]}
                y={i % 2 === 0 ? 14 : 54}
                font-size="11"
                font-family={FONT}
                fill="#4f5257"
                text-anchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
              />
            {/each}
            <rect x="320" y="20" width="5" height="20" fill="#0d0d0d" />
            {@render roundel(343, 30, route.terminus.label)}
          </svg>
        {/if}
        {#if studio.selectedRow === s.row_id && doubt !== undefined}
          {@const rides = rule?.leaf_summary.find((line) =>
            line.row_ids.includes(doubt.row),
          )?.label}
          <div class="reading" aria-live="polite">
            <p class="claim">
              Labelled {@render bullet(doubt.given)}<strong
                >{doubt.given}</strong
              >, it rides the {rides ?? 'no answer'} line. The model reads it as
              {@render bullet(doubt.likely)}<strong>{doubt.likely}</strong>.
            </p>
            <dl class="cells">
              {#each values(doubt.row) as [name, value] (name)}
                <div>
                  <dt>{name}</dt>
                  <dd>{value}</dd>
                </div>
              {/each}
            </dl>
            <div class="acts">
              <button
                type="button"
                class="button button-solid"
                onclick={() => {
                  void onfix(doubt);
                }}>Change to {doubt.likely}</button
              >
              <button
                type="button"
                class="button"
                onclick={() => {
                  studio.toggleKept(doubt.row);
                  studio.selectedRow = null;
                  onidle();
                }}>Keep {doubt.given}</button
              >
            </div>
          </div>
        {/if}
      </li>
    {/each}
  </ol>
  {#if thin.length > 0}
    <p class="thin">
      Not drawn, too few values to place on a line:
      {#each thin as item, i (item.suspect.row_id)}{i > 0 ? ', ' : ''}row
        {item.suspect.row_id} ({sparse.get(item.suspect.row_id)}){/each}.
    </p>
  {/if}
{/if}

<style>
  .doubts {
    border-top: var(--rule);
    margin-top: var(--space-2);
  }
  .doubt {
    border-bottom: 1px solid var(--line);
  }
  .doubt > button {
    appearance: none;
    display: grid;
    grid-template-columns: 1.5rem 4.2rem minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: 0.4rem 0.25rem;
    border: 0;
    background: transparent;
    text-align: left;
    font-size: var(--step--1);
    cursor: pointer;
    overflow-wrap: anywhere;
  }
  .doubt > button:hover:not(:disabled),
  .doubt.on > button {
    background: var(--sheet-quiet);
  }
  .doubt > button:disabled {
    cursor: default;
    color: var(--ink-2);
  }
  .doubt.on > button {
    box-shadow: inset 3px 0 0 var(--ink);
  }
  .row {
    font-weight: 700;
  }
  .what {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .what > span {
    min-width: 0;
  }
  .given {
    color: var(--ink-2);
  }
  .pct {
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .roundel {
    display: inline-grid;
    place-items: center;
    width: 1.4rem;
    height: 1.4rem;
    border-radius: 50%;
    background: var(--ink);
    color: var(--on-ink);
    font-size: 0.6875rem;
    font-weight: 700;
    flex: none;
  }
  .quiet .roundel {
    background: var(--sheet);
    color: var(--ink);
    box-shadow: inset 0 0 0 1.5px var(--ink);
  }
  .arrow {
    width: 0.85rem;
    height: 0.6rem;
    margin: 0 0.15rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    flex: none;
  }
  .reading {
    display: grid;
    gap: var(--space-3);
    padding: var(--space-2) 0.25rem var(--space-3) 2.2rem;
    font-size: var(--step--1);
    box-shadow: inset 3px 0 0 var(--ink);
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .claim {
    font-size: var(--step-0);
    line-height: 1.6;
  }
  .cells {
    display: grid;
    gap: 0.15rem;
    margin: var(--space-1) 0 0 5px;
    border-left: 2px solid var(--ink);
    padding-left: var(--space-3);
    font-variant-numeric: tabular-nums;
  }
  .cells div {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    align-items: baseline;
    gap: var(--space-3);
  }
  .cells div::before {
    content: '';
    position: absolute;
    left: calc(-1 * var(--space-3) - 5px);
    top: 0.62em;
    width: 8px;
    height: 2px;
    background: var(--ink);
  }
  .cells dd {
    grid-column: 1;
    grid-row: 1;
    min-width: 0;
    font-size: var(--step--1);
    font-weight: 700;
  }
  .cells dt {
    grid-column: 2;
    grid-row: 1;
    font-size: var(--step--1);
    color: var(--ink-2);
  }
  .acts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .acts .button {
    min-width: 0;
    max-width: 100%;
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .thin {
    font-size: var(--step--1);
    color: var(--ink-2);
  }
  .strip {
    display: block;
    width: 100%;
    height: auto;
    margin: 0.1rem 0 var(--space-2);
  }
  @media (max-width: 40rem) {
    .reading {
      padding-left: var(--space-4);
    }
  }
</style>
