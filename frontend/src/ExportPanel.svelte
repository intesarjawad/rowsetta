<script lang="ts">
  import {
    EXPORT_FORMATS,
    SQL_DIALECTS,
    type ExportFormat,
    type SqlDialect,
  } from './backend/types';
  import { DEFAULT_RULE_DEPTH, RULE_DEPTHS } from './rule';
  import RuleView from './RuleView.svelte';
  import type { Studio } from './state.svelte';

  let { studio }: { studio: Studio } = $props();

  const FORMAT_NAMES: Record<ExportFormat, string> = {
    sql: 'SQL',
    dbt: 'dbt',
    python: 'Python',
    json: 'JSON',
  };
  const DIALECT_NAMES: Record<SqlDialect, string> = {
    duckdb: 'DuckDB',
    postgres: 'PostgreSQL',
    sqlite: 'SQLite',
  };
  const COPY_REFUSED = {
    error: 'The browser did not allow copying.',
    next_step: 'Select the text and copy it with Ctrl+C or Cmd+C.',
  };

  let depth = $state(DEFAULT_RULE_DEPTH);
  const query = $derived(studio.exportQuery);
  const exported = $derived(studio.exported);
  const files = $derived(
    exported === null
      ? []
      : exported.format === 'dbt'
        ? Object.entries(exported.files)
        : [[FORMAT_NAMES[exported.format], exported.text] as const],
  );

  async function copy(name: string, text: string): Promise<void> {
    if (studio.refitting || studio.exportStale) return;
    try {
      await navigator.clipboard.writeText(text);
      studio.announcement = { text: `Copied ${name}` };
    } catch {
      studio.exportProblem = COPY_REFUSED;
    }
  }
</script>

<section class="panel panel--export" aria-labelledby="export-heading">
  <h2 id="export-heading">Export</h2>
  <div class="controls">
    <fieldset class="segments">
      <legend>Tree depth</legend>
      {#each RULE_DEPTHS as option (option)}
        <label>
          <input
            type="radio"
            name="rule-depth"
            value={option}
            bind:group={depth}
          />
          {option}
        </label>
      {/each}
    </fieldset>
    <button
      type="button"
      class="button button-solid"
      disabled={studio.refitting}
      onclick={() => {
        void studio.exportRule(depth);
      }}
    >
      Export rule
    </button>
  </div>
  {#if studio.refitting}<p role="status">
      Wait for the model update before exporting.
    </p>{/if}
  {#if studio.exportStale}
    <p role="status" class="alert">
      The previous export and certificate are stale because the inputs changed.
      Export the rule again to regenerate them.
    </p>
  {/if}
  <RuleView {studio} />
  {#if studio.certificate.length > 0}
    <h3>Certificate</h3>
    <ul class="certificate" aria-label="Certificate">
      {#each studio.certificate as figure, index (index)}
        <li>{figure}</li>
      {/each}
    </ul>
  {/if}
  {#if exported !== null || studio.exportProblem !== null}
    <fieldset class="segments">
      <legend>Format</legend>
      {#each EXPORT_FORMATS as format (format)}
        <label>
          <input
            type="radio"
            name="export-format"
            value={format}
            checked={query.format === format}
            disabled={studio.refitting}
            onchange={() => {
              void studio.showExport({ ...query, format });
            }}
          />
          {FORMAT_NAMES[format]}
        </label>
      {/each}
    </fieldset>
    {#if query.format === 'sql' || query.format === 'dbt'}
      <fieldset class="segments">
        <legend>Dialect</legend>
        {#each SQL_DIALECTS as dialect (dialect)}
          <label>
            <input
              type="radio"
              name="export-dialect"
              value={dialect}
              checked={query.dialect === dialect}
              disabled={studio.refitting}
              onchange={() => {
                void studio.showExport({ ...query, dialect });
              }}
            />
            {DIALECT_NAMES[dialect]}
          </label>
        {/each}
      </fieldset>
    {/if}
    {#if studio.exportProblem !== null}
      <div role="alert" class="alert">
        <p>{studio.exportProblem.error}</p>
        <p>{studio.exportProblem.next_step}</p>
        <p>Choose another format above to export this rule.</p>
      </div>
    {/if}
    {#each files as [name, text] (name)}
      <h3>{name}</h3>
      <pre>{text}</pre>
      <button
        type="button"
        class="button"
        disabled={studio.refitting || studio.exportStale}
        onclick={() => {
          void copy(name, text);
        }}
      >
        Copy {name}
      </button>
    {/each}
  {/if}
</section>

<style>
  pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-3);
  }
  .certificate {
    display: grid;
    gap: 2px;
    border: 2px solid var(--ink);
    background: var(--sheet-quiet);
    padding: var(--space-3);
    font-family: var(--font-ui);
    font-size: var(--step--1);
    overflow-wrap: anywhere;
  }
</style>
