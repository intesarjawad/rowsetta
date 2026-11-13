<script lang="ts">
  import type { LeakHint } from './backend/types';
  import type { Studio } from './state.svelte';

  let { studio }: { studio: Studio } = $props();

  const refitGeneration = $derived(studio.workspace?.refit_generation ?? null);
  const excluded = $derived(studio.workspace?.excluded_columns ?? []);

  // A column can fail more than one check; it is listed once with every reason.
  const byColumn = $derived(
    studio.leaks.reduce((columns, hint) => {
      columns.set(hint.column, [...(columns.get(hint.column) ?? []), hint]);
      return columns;
    }, new Map<string, LeakHint[]>()),
  );

  $effect(() => {
    if (refitGeneration !== null) void studio.checkLeaks();
  });
</script>

<section class="panel panel--leak" aria-labelledby="leak-heading">
  <h2 id="leak-heading">Columns that may leak the answer</h2>
  <p class="hint">
    These checks catch identifiers and near-copies of the label, not every
    column recorded after the outcome. They run once 30 rows have human labels.
  </p>
  {#if byColumn.size === 0}
    <p class="clear">No column flagged.</p>
  {:else}
    <ul class="columns">
      {#each byColumn as [column, hints] (column)}
        {@const isExcluded = excluded.includes(column)}
        <li class="column">
          {#if isExcluded}
            <s class="name">{column}</s> (excluded)
          {:else}
            <span class="name">{column}</span>
          {/if}
          <ul class="reasons">
            {#each hints as hint (hint.kind)}
              <li>{hint.reason}</li>
            {/each}
          </ul>
          <button
            type="button"
            class="button"
            onclick={() => {
              void studio.exclude(column, !isExcluded);
            }}
          >
            {isExcluded ? 'Include' : 'Exclude'} column {column}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .columns {
    display: grid;
    gap: var(--space-3);
  }
  .column {
    display: grid;
    gap: var(--space-2);
    justify-items: start;
    padding: var(--space-3);
    border: 1px solid var(--line);
  }
  .name {
    font-family: var(--font-ui);
    font-weight: 700;
    overflow-wrap: anywhere;
  }
  .reasons {
    color: var(--ink-2);
    font-size: var(--step--1);
    display: grid;
    gap: var(--space-1);
  }
  .clear {
    font-weight: 600;
  }
</style>
