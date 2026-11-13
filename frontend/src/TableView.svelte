<script lang="ts">
  import { tick, untrack } from 'svelte';
  import type { Cell } from './backend/types';
  import { shownSuspects } from './audit';
  import LabelMenu from './LabelMenu.svelte';
  import {
    missingText,
    rowLabel,
    rowLabelText,
    tableCommand,
  } from './labelling';
  import { lineColour } from './palette';
  import { columnDecimals, disagreementLines } from './rule';
  import type { Studio } from './state.svelte';

  let { studio }: { studio: Studio } = $props();

  const workspace = $derived(studio.workspace);
  const page = $derived(studio.page);
  const loaded = $derived(workspace?.loaded ?? false);
  const target = $derived(workspace?.target ?? null);
  const classes = $derived(workspace?.classes ?? []);
  const human = $derived(workspace?.human ?? {});
  const missing = $derived(missingText(workspace?.missing ?? {}));
  const columns = $derived(
    page?.columns.filter((column) => column.name !== target) ?? [],
  );
  const mode = $derived(studio.mode);
  const ruleLines = $derived(disagreementLines(studio.rule));
  const suspects = $derived(shownSuspects(studio.suspects, human, studio.kept));
  const decimals = $derived(columnDecimals(page?.rows ?? []));

  // Roving focus: only the active row's label cell is in the tab order.
  let active = $state(0);
  let menuRow = $state<number | null>(null);
  const cells: (HTMLButtonElement | null)[] = [];

  function chipText(state: ReturnType<typeof rowLabel>): {
    lead: string;
    word: string;
    tail: string;
  } {
    const stale =
      state.kind === 'human' || state.kind === 'unlabelled'
        ? false
        : state.stale;
    const tail = stale ? ', updating' : '';
    switch (state.kind) {
      case 'human':
        return { lead: 'Labelled ', word: state.label, tail };
      case 'proposed':
        return { lead: 'Proposed ', word: state.label, tail };
      case 'unsure':
        return { lead: '', word: 'Unsure', tail };
      case 'unlabelled':
        return { lead: 'Unlabelled', word: '', tail };
    }
  }

  /** One fixed precision per column, so decimals line up down the page. */
  function show(value: Cell | undefined, column: string): string {
    const places = decimals.get(column);
    return typeof value === 'number' && places !== undefined && places <= 12
      ? value.toFixed(places)
      : display(value);
  }

  /** Read a doubted row on the map: the lens travels to its thread. */
  function pick(rowId: number): void {
    studio.selectedRow = rowId;
    const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
    document
      .getElementById('interchange')
      ?.scrollIntoView({ block: 'start', behavior: calm ? 'auto' : 'smooth' });
  }

  $effect(() => {
    // Only a newly loaded table resets the page; filters choose their own.
    if (loaded) void untrack(() => studio.showPage(0));
  });

  $effect(() => {
    const index = page?.row_ids.indexOf(studio.focusRow ?? -1) ?? -1;
    if (index === -1) return;
    studio.focusRow = null;
    // The new page's cells are bound after this effect runs.
    void tick().then(() => {
      focusRow(index);
    });
  });

  // Evaluation takes a label for the served row only; the others stay inert.
  function inert(rowId: number): boolean {
    return mode.kind === 'evaluate' && rowId !== mode.row;
  }

  function display(value: Cell | undefined): string {
    return value === null || value === undefined ? '' : String(value);
  }

  function showPage(index: number): void {
    active = 0;
    menuRow = null;
    void studio.showPage(index);
  }

  function focusRow(index: number): void {
    const cell = cells[index];
    if (!cell) return;
    active = index;
    cell.focus();
  }

  function onCellKey(event: KeyboardEvent, index: number, rowId: number): void {
    const command = tableCommand(event);
    if (command === null) return;
    event.preventDefault();
    switch (command.kind) {
      case 'move':
        focusRow(index + command.by);
        break;
      case 'label': {
        const label = classes[command.classIndex];
        if (label !== undefined) void studio.label(rowId, label);
        break;
      }
      case 'undo':
        void studio.undo();
        break;
      case 'next':
        void studio.nextSuggested();
        break;
      case 'evaluate':
        void studio.toggleEvaluation();
        break;
      case 'keys':
        studio.keySheetOpen = true;
        break;
    }
  }

  function closeMenu(index: number, label?: string | null): void {
    const rowId = menuRow;
    menuRow = null;
    if (rowId !== null && label !== undefined) void studio.label(rowId, label);
    focusRow(index);
  }
</script>

<section class="sheet" aria-labelledby="table-heading">
  <h2 id="table-heading" class="visually-hidden">Rows</h2>
  {#if target === null}
    <p class="note-line">Choose a target column to start labelling.</p>
  {:else if missing !== ''}
    <p class="note-line">{missing}</p>
  {/if}
  {#if studio.refit !== null}
    <p class="refit">
      Updating proposals{#if studio.refit.total !== null}, {studio.refit.done}
        of {studio.refit.total} rows{/if}
    </p>
    {#if studio.refit.total === null}
      <progress aria-label="Updating proposals"></progress>
    {:else}
      <progress
        aria-label="Updating proposals"
        max={studio.refit.total}
        value={studio.refit.done}
      ></progress>
    {/if}
  {/if}
  {#if studio.filter !== null}
    <p class="filter-bar">
      <span>{studio.filter.description}.</span>
      <button
        type="button"
        class="button"
        onclick={() => {
          void studio.filterRows(null);
        }}
      >
        Show all rows
      </button>
    </p>
  {/if}
  {#if page !== null}
    {@const first = page.page * page.size}
    <!-- A scrollable region must take focus, or a keyboard cannot reach cells past its edge. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="scroll" role="region" aria-label="Table rows" tabindex="0">
      <table aria-rowcount={page.total + 1}>
        <caption>
          Rows {first + 1} to {first + page.row_ids.length} of {page.total}
        </caption>
        <thead>
          <tr aria-rowindex={1}>
            <th scope="col" class="id">Row</th>
            {#each columns as column (column.name)}
              <th
                scope="col"
                class:num={column.kind === 'numeric'}
                title={column.name}>{column.name.replaceAll('_', ' ')}</th
              >
            {/each}
            {#if target !== null}
              <th scope="col" class="label-col" title={target}>{target}</th>
            {/if}
          </tr>
        </thead>
        <tbody>
          {#each page.row_ids as rowId, index (rowId)}
            {@const info = suspects.get(rowId)}
            {@const drawn = info !== undefined && info.state !== 'fixed'}
            {@const label = rowLabel(rowId, human, studio.proposals)}
            {@const text = chipText(label)}
            <tr
              id={`row-${String(rowId)}`}
              aria-rowindex={first + index + 2}
              class:suspect={drawn && info.state === 'open'}
              class:disagrees={drawn &&
                info.state === 'open' &&
                info.suspect.given !== info.suspect.likely}
              class:selected={studio.selectedRow === rowId}
              class:filtered={studio.filter !== null}
            >
              <th scope="row" class="id"
                >{rowId}{#if drawn && info.state === 'open'}<span
                    class="rank"
                    aria-hidden="true">{info.rank + 1}</span
                  >{/if}</th
              >
              {#each columns as column (column.name)}
                {@const value = page.rows[index]?.[column.name]}
                <td
                  class:num={typeof value === 'number'}
                  title={typeof value === 'string' ? value : undefined}
                >
                  {show(value, column.name)}
                </td>
              {/each}
              {#if target !== null}
                <td class="label-col">
                  <div class="cellbox">
                    <button
                      bind:this={cells[index]}
                      type="button"
                      class={`chip chip--${label.kind}`}
                      class:chip--stale={label.kind !== 'human' &&
                        label.kind !== 'unlabelled' &&
                        label.stale}
                      title={rowLabelText(label)}
                      tabindex={index === active ? 0 : -1}
                      aria-haspopup="listbox"
                      aria-disabled={inert(rowId) ? 'true' : undefined}
                      aria-expanded={menuRow === rowId}
                      aria-controls={menuRow === rowId
                        ? 'label-menu'
                        : undefined}
                      onfocus={() => {
                        active = index;
                      }}
                      onclick={() => {
                        if (!inert(rowId)) menuRow = rowId;
                      }}
                      onkeydown={(event) => {
                        onCellKey(event, index, rowId);
                      }}
                      ><span class="visually-hidden">{text.lead}</span
                      >{#if label.kind === 'human' || label.kind === 'proposed'}<span
                          class="dot"
                          style:--route={lineColour(classes, label.label)}
                          aria-hidden="true"
                        ></span>{/if}<span class="word">{text.word}</span><span
                        class="visually-hidden">{text.tail}</span
                      ></button
                    >
                    {#if mode.kind === 'evaluate' && mode.row === rowId}
                      <span class="note">Evaluation row: label it blind</span>
                    {/if}
                    {#if ruleLines.has(rowId) && !(mode.kind === 'evaluate' && mode.row === rowId)}
                      <span class="note"
                        >Rule line {ruleLines.get(rowId)} disagrees</span
                      >
                    {/if}
                    {#if drawn}
                      <button
                        type="button"
                        class="mark"
                        class:mark--stet={info.state === 'stet'}
                        tabindex="-1"
                        aria-label={`Read row ${String(rowId)} on the map`}
                        onclick={() => {
                          pick(rowId);
                        }}
                      >
                        {#if info.state === 'stet'}
                          kept
                        {:else}
                          reads <span
                            class="bullet"
                            style:background={lineColour(
                              classes,
                              info.suspect.likely,
                            )}
                            aria-hidden="true"
                            >{info.suspect.likely.slice(0, 1)}</span
                          >
                          {info.suspect.likely}
                        {/if}
                      </button>
                    {/if}
                  </div>
                  {#if info?.state === 'open'}
                    <span class="visually-hidden"
                      >Check: model says {info.suspect.likely}</span
                    >
                  {/if}
                  {#if menuRow === rowId}
                    <LabelMenu
                      id="label-menu"
                      {rowId}
                      {classes}
                      current={human[String(rowId)] ?? null}
                      onpick={(picked: string | null) => {
                        closeMenu(index, picked);
                      }}
                      oncancel={() => {
                        closeMenu(index);
                      }}
                      onleave={() => {
                        menuRow = null;
                      }}
                    />
                  {/if}
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <nav aria-label="Table pages">
      <button
        type="button"
        class="button"
        disabled={page.page === 0}
        onclick={() => {
          showPage(page.page - 1);
        }}
        aria-label="Previous page"
      >
        Previous
      </button>
      <button
        type="button"
        class="button"
        disabled={first + page.size >= page.total}
        onclick={() => {
          showPage(page.page + 1);
        }}
        aria-label="Next page"
      >
        Next
      </button>
      <span class="where"
        >Rows {first + 1} to {first + page.row_ids.length} of {page.total}</span
      >
    </nav>
  {/if}
</section>

<style>
  .sheet {
    --header-height: 2.25rem;
    grid-area: table;
    background: var(--sheet);
    border: 2px solid var(--ink);
    border-right: 1px solid var(--ink);
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
  }
  .note-line {
    padding: var(--space-3) var(--space-4);
    font-weight: 600;
    color: var(--ink-2);
  }
  .refit {
    padding: var(--space-2) var(--space-4) 0;
    font-size: var(--step--1);
    font-weight: 600;
    color: var(--ink-2);
  }
  .filter-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    background: var(--ink);
    color: var(--on-ink);
    padding: var(--space-2) var(--space-3);
    font-weight: 600;
  }
  .filter-bar .button {
    color: var(--ink);
  }
  .scroll {
    overflow: auto;
    flex: 1;
    min-height: 0;
    scrollbar-gutter: stable;
    /* Rows stop under the header, never half-cut beneath it. */
    scroll-snap-type: y proximity;
    scroll-padding-top: var(--header-height);
  }
  tbody tr {
    scroll-snap-align: start;
  }
  table {
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    min-width: max-content;
    font-family: var(--font-ui);
    font-size: var(--step--1);
    font-variant-numeric: tabular-nums;
  }
  caption {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  th,
  td {
    padding: 0.42rem 0.9rem;
    text-align: left;
    white-space: nowrap;
    border-bottom: 1px solid var(--line);
    background: var(--sheet);
  }
  td:not(.num):not(.label-col) {
    max-width: 22ch;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  thead th {
    max-width: 22ch;
    white-space: normal;
    overflow-wrap: anywhere;
    position: sticky;
    top: 0;
    z-index: 3;
    background: var(--ink);
    color: var(--on-ink);
    font-weight: 600;
    border-bottom: 0;
    height: var(--header-height);
    padding-block: 0;
    box-shadow: 0 -1px 0 var(--ink);
  }
  .num {
    text-align: right;
  }
  .id {
    position: sticky;
    left: 0;
    z-index: 1;
    color: var(--ink-3);
    font-weight: 500;
    text-align: right;
    border-right: 1px solid var(--line);
  }
  thead .id {
    z-index: 4;
    color: var(--on-ink-quiet);
    border-right: 0;
  }
  .label-col {
    position: sticky;
    right: 0;
    z-index: 1;
    min-width: 11rem;
    border-left: 1px solid var(--line);
    font-family: var(--font-ui);
  }
  thead .label-col {
    z-index: 4;
    font-family: var(--font-ui);
    border-left: 0;
  }
  tbody tr:hover > * {
    background: var(--sheet-quiet);
  }
  .cellbox {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  /* A label is its class on its line's mark: a solid dot when a person gave
     it, a ring when the rule proposed it, a dashed ring when the rule is unsure. */
  .chip {
    appearance: none;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-family: var(--font-ui);
    font-size: var(--step--1);
    font-weight: 600;
    line-height: 1.1;
    padding: 0.26rem 0.2rem;
    border: 0;
    background: transparent;
    color: var(--ink);
    max-width: 14rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: middle;
  }
  .dot {
    flex: none;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 50%;
    background: var(--route);
  }
  .chip--proposed .dot {
    background: transparent;
    border: 2px solid var(--route);
  }
  .chip:hover .word {
    text-decoration: underline;
    text-underline-offset: 0.2em;
  }
  .chip--proposed {
    color: var(--ink-2);
    font-weight: 500;
    font-style: italic;
  }
  .chip--unsure {
    color: var(--ink-2);
    font-weight: 500;
  }
  .chip--unsure::before {
    content: '';
    flex: none;
    width: 0.7rem;
    height: 0.7rem;
    box-sizing: border-box;
    border-radius: 50%;
    border: 2px dashed var(--ink-3);
  }
  .chip--unlabelled {
    color: var(--ink-3);
  }
  /* No label yet: a short stretch of track with no line colour. */
  .chip--unlabelled::before {
    content: '';
    width: 0.9rem;
    height: 2px;
    background: currentColor;
  }
  .chip--stale {
    opacity: 0.8;
  }
  .chip[aria-disabled='true'] {
    cursor: default;
    opacity: 0.55;
  }
  .word {
    position: relative;
  }
  .note {
    font-family: var(--font-ui);
    font-size: var(--step--1);
    color: var(--ink-2);
  }
  nav {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-top: 1px solid var(--line);
  }
  /* Paging is a pair of words on a rule, not two more boxes. */
  nav .button {
    border-width: 0 0 2px;
    background: transparent;
    padding: 0.2rem 0;
    margin-right: var(--space-3);
  }
  nav .button:disabled {
    border-color: var(--line);
  }
  .where {
    margin-left: auto;
    font-size: var(--step--1);
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
  }

  /* A doubted row: its rank roundel, and the line the model reads it on. */
  tr.suspect > .id {
    color: var(--ink);
    font-weight: 700;
  }
  .rank {
    display: inline-grid;
    place-items: center;
    width: 1.35rem;
    height: 1.35rem;
    margin-left: 0.45rem;
    border-radius: 50%;
    background: var(--ink);
    color: var(--on-ink);
    font-family: var(--font-ui);
    font-size: 0.6875rem;
    font-weight: 700;
    vertical-align: middle;
  }
  tr.disagrees .word {
    text-decoration: line-through;
    text-decoration-thickness: 2px;
  }
  tr.selected > * {
    box-shadow:
      inset 0 2px 0 var(--ink),
      inset 0 -2px 0 var(--ink);
  }
  tr.filtered > .id {
    box-shadow: inset 4px 0 0 var(--ink);
  }
  .mark {
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    background: transparent;
    border: 0;
    padding: 0.2rem 0;
    cursor: pointer;
    font-family: var(--font-ui);
    font-size: var(--step--1);
    font-weight: 500;
    color: var(--ink-2);
    white-space: nowrap;
  }
  .mark:hover {
    color: var(--ink);
    text-decoration: underline;
  }
  .mark--stet {
    font-weight: 700;
    color: var(--ink);
  }
  .bullet {
    display: inline-grid;
    place-items: center;
    width: 1.1rem;
    height: 1.1rem;
    border-radius: 50%;
    color: #fff;
    font-size: 0.625rem;
    font-weight: 700;
  }

  @media (max-width: 62rem) {
    .sheet {
      border-right: 2px solid var(--ink);
      height: min(72dvh, 40rem);
    }
    .label-col {
      min-width: 8.5rem;
    }
    th,
    td {
      padding-inline: 0.6rem;
    }
  }
</style>
