<script lang="ts">
  import type { LeafLine } from './backend/types';
  import { lineColour } from './palette';
  import { lineFilter, ruleLineParts } from './rule';
  import type { Studio } from './state.svelte';

  let { studio }: { studio: Studio } = $props();

  const rule = $derived(studio.rule);
  const stale = $derived(
    rule !== null && rule.generation !== studio.workspace?.generation,
  );

  function show(line: LeafLine): void {
    void studio.filterRows(lineFilter(line));
  }
</script>

{#if rule !== null}
  <section class="rule" aria-labelledby="rule-heading">
    <h3 id="rule-heading">Rule</h3>
    {#if stale}
      <p class="stale">Labels changed since this rule was fitted.</p>
    {/if}
    <p class="hint">
      Focus a line to show its rows in the table; Escape shows every row.
    </p>
    <ol>
      {#each rule.leaf_summary as line (line.line_no)}
        {@const parts = ruleLineParts(line, studio.ruleDecimals)}
        <li>
          <button
            type="button"
            class="line"
            class:abstains={line.label === null}
            style:--route={line.label === null
              ? 'transparent'
              : lineColour(studio.workspace?.classes ?? [], line.label)}
            onfocus={() => {
              show(line);
            }}
            onmouseenter={() => {
              show(line);
            }}
            onclick={() => {
              show(line);
            }}
            onkeydown={(event) => {
              if (event.key !== 'Escape') return;
              event.preventDefault();
              void studio.filterRows(null);
            }}
          >
            <span class="no">Line {line.line_no}:</span>
            <!-- Each line is drawn as a strip map: its tests are the stops, its answer the terminus. -->
            <span class="strip">
              {#each parts.conditions.split(' · ') as stop, i (i)}
                <span class="stop"
                  >{#if i > 0}<span class="visually-hidden"
                      >,
                    </span>{/if}{stop}</span
                >
              {/each}
              <span class="end">
                <span class="visually-hidden"> → </span>
                {#if parts.answer === null}
                  <span class="then"
                    ><span class="bullet open" aria-hidden="true"></span>no
                    answer (rule unsure)</span
                  >
                {:else}
                  <span class="then"
                    ><span class="bullet" aria-hidden="true"
                      >{parts.answer.slice(0, 1)}</span
                    >{parts.answer}</span
                  >
                {/if}
                <span class="visually-hidden">: </span>
                <span class="stats">
                  {parts.rows}{#if parts.answer !== null}, {parts.agreeing}{/if}
                </span>
              </span>
            </span>
          </button>
        </li>
      {/each}
    </ol>
  </section>
{/if}

<style>
  .rule {
    display: grid;
    gap: var(--space-2);
  }
  .rule h3 {
    font-size: var(--step-0);
    font-weight: 700;
  }
  .stale {
    font-weight: 700;
    color: var(--ink);
  }
  ol {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    border-top: var(--rule);
  }
  ol li {
    max-width: none;
  }
  li {
    border-bottom: 1px solid var(--line);
  }
  /* Each line of the rule is a strip map in its line colour, as on the map. */
  .line {
    appearance: none;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: var(--space-3);
    width: 100%;
    text-align: left;
    background: var(--sheet);
    border: 0;
    padding: var(--space-3) var(--space-3) var(--space-3) 0;
    cursor: pointer;
    transition: background var(--lift-ms);
  }
  .line:hover,
  .line:focus-visible {
    background: var(--sheet-quiet);
  }
  .line:focus-visible {
    outline: 2px solid var(--ink);
    outline-offset: -2px;
  }
  .no {
    font-family: var(--font-ui);
    font-size: var(--step--1);
    font-weight: 700;
    padding-top: 0.1rem;
    color: var(--ink-3);
    min-width: 5.2ch;
  }
  .strip {
    position: relative;
    display: grid;
    gap: 0.35rem;
    padding-left: 1.6rem;
  }
  /* The track runs from each stop to the next, and from the last into the terminus bar. */
  .stop::after,
  .end::after {
    content: '';
    position: absolute;
    left: calc(-1.6rem + 0.4rem);
    width: 5px;
    background: var(--route);
  }
  .stop::after {
    top: calc(0.3rem + 6px);
    height: calc(100% + 0.35rem);
  }
  .end::after {
    top: 0;
    height: calc(0.85rem + 2.5px);
  }
  .abstains .stop::after,
  .abstains .end::after {
    background: var(--ink-3);
  }
  .stop {
    position: relative;
    font-family: var(--font-ui);
    font-size: var(--step--1);
    overflow-wrap: anywhere;
  }
  .stop::before {
    content: '';
    position: absolute;
    left: calc(-1.6rem + 0.4rem + 2.5px - 6px);
    top: 0.3rem;
    width: 12px;
    height: 12px;
    box-sizing: border-box;
    border-radius: 50%;
    background: #ffffff;
    border: 2px solid var(--ink);
    z-index: 1;
  }
  .end {
    position: relative;
    display: grid;
    gap: 2px;
    padding-top: 0.35rem;
  }
  .end::before {
    content: '';
    position: absolute;
    left: calc(-1.6rem + 0.4rem + 2.5px - 9px);
    top: 0.85rem;
    width: 18px;
    height: 5px;
    background: var(--ink);
    z-index: 1;
  }
  .then {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    justify-self: start;
    font-size: var(--step-1);
    font-weight: 700;
    letter-spacing: -0.01em;
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .bullet {
    display: inline-grid;
    place-items: center;
    width: 1.3rem;
    height: 1.3rem;
    border-radius: 50%;
    background: var(--route);
    color: #ffffff;
    font-size: 0.6875rem;
    flex: none;
  }
  .bullet.open {
    background: transparent;
    border: 2px dashed var(--ink-2);
    box-sizing: border-box;
  }
  .abstains .then {
    color: var(--ink-2);
    font-size: var(--step-0);
    font-weight: 500;
  }
  .stats {
    font-size: var(--step--1);
    color: var(--ink-2);
  }
</style>
