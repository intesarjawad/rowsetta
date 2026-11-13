<script lang="ts">
  import type { Studio } from './state.svelte';
  import { BROWSER } from './browser/config';

  let { studio }: { studio: Studio } = $props();

  // Mirror MIN_CLASSES and MAX_CLASSES in src/rowsetta/core/session.py.
  const MIN_CLASSES = 2;
  const MAX_CLASSES = 10;

  const workspace = $derived(studio.workspace);
  const target = $derived(workspace?.target ?? null);
  const humanCount = $derived(Object.keys(workspace?.human ?? {}).length);
  const columns = $derived(studio.page?.columns ?? []);
  const validColumn = $derived(
    columns.some((option) => option.name === column),
  );

  let chosenFile = $state<string | null>(null);
  let column = $state<string | undefined>(undefined);
  let newName = $state('');
  let newClasses = $state('');
  let classProblem = $state<string | null>(null);
  /** Set after a column's values become labels, so the rows left out can be counted. */
  let prefilled = $state<{ column: string; unlabelled: number } | null>(null);

  async function open(files: FileList | null | undefined): Promise<void> {
    const file = files?.[0];
    if (file === undefined) return;
    await studio.upload(file);
    if (studio.problem === null) {
      chosenFile = file.name;
      column = undefined;
      prefilled = null;
    }
  }

  async function useColumn(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const chosen = column;
    if (chosen === undefined || !validColumn) return;
    await studio.chooseTarget({ target: chosen });
    const total = studio.rowCount;
    prefilled =
      studio.problem === null && total !== null
        ? { column: chosen, unlabelled: total - humanCount }
        : null;
  }

  function createTarget(event: SubmitEvent): void {
    event.preventDefault();
    const classes = [
      ...new Set(
        newClasses
          .split(',')
          .map((name) => name.trim())
          .filter((name) => name !== ''),
      ),
    ];
    if (classes.length < MIN_CLASSES || classes.length > MAX_CLASSES) {
      classProblem = `Name ${String(MIN_CLASSES)} to ${String(MAX_CLASSES)} different classes, separated by commas.`;
      return;
    }
    classProblem = null;
    prefilled = null;
    void studio.chooseTarget({ target: newName.trim(), classes });
  }

  function teachFromScratch(): void {
    if (target === null || workspace === null) return;
    prefilled = null;
    void studio.chooseTarget({ target, classes: workspace.classes });
  }
</script>

<section class="panel panel--target" aria-labelledby="target-heading">
  <h2 id="target-heading">Table and target</h2>
  {#if studio.recovery?.problem}
    <div role="alert" class="recovery"><p>{studio.recovery.problem}</p></div>
  {/if}
  {#if studio.recovery?.pending}
    <section class="recovery" aria-label="Saved labels">
      <p>
        {studio.recovery.pending.count} saved {studio.recovery.pending.count ===
        1
          ? 'label'
          : 'labels'} for this table and target.
      </p>
      <button
        type="button"
        class="button button-solid"
        onclick={() => {
          void studio.restoreLabels();
        }}>Restore labels</button
      >
      <button
        type="button"
        class="button"
        onclick={() => {
          studio.recovery?.discard();
        }}>Discard saved labels</button
      >
    </section>
  {/if}
  {#if workspace?.loaded !== true}
    <p class="lede">
      Open a CSV, label a few rows, and keep a rule that labels the rest. The
      table stays on this machine.
    </p>
  {/if}
  <div
    class="drop"
    role="group"
    aria-labelledby="drop-heading"
    ondragover={(event) => {
      event.preventDefault();
    }}
    ondrop={(event) => {
      event.preventDefault();
      void open(event.dataTransfer?.files);
    }}
  >
    <h3 id="drop-heading">Open a CSV</h3>
    <!-- The file is where every row enters, so it is drawn as the map's origin. -->
    <label class="origin">
      <span class="dot" aria-hidden="true"></span>
      <span>Choose or drop a CSV file</span>
      <input
        class="visually-hidden"
        type="file"
        accept=".csv,text/csv"
        onchange={(event) => {
          void open(event.currentTarget.files);
        }}
      />
    </label>
    {#if chosenFile === null}
      <p class="hint">
        Text columns inferred as free text are skipped when more than half of
        their values are distinct. Lower-cardinality text can remain a feature.
      </p>
    {:else}
      <p class="hint">Opened {chosenFile}.</p>
    {/if}
  </div>

  {#if workspace?.loaded === true}
    {#if target !== null}
      <p class="target-line">
        Target: {target} ({workspace.classes.join(', ')}). {humanCount} human labels.
      </p>
    {/if}
    {#if prefilled !== null}
      <p class="hint">
        Took the labels from {prefilled.column}; {prefilled.unlabelled} rows with
        no value stay unlabelled.
      </p>
    {/if}
    {#if target !== null && humanCount > 0}
      <button type="button" class="button" onclick={teachFromScratch}>
        Clear all and teach from scratch
      </button>
    {/if}

    {#if !BROWSER}<form class="stack" onsubmit={useColumn}>
        <fieldset class="segments">
          <legend>Existing column</legend>
          {#each columns as option (option.name)}
            <label>
              <input
                type="radio"
                name="target-column"
                value={option.name}
                bind:group={column}
              />
              {option.name.replaceAll('_', ' ')}
              <span class="visually-hidden">({option.kind})</span>
            </label>
          {/each}
        </fieldset>
        <button type="submit" class="button" disabled={!validColumn}
          >Use its values as labels</button
        >
      </form>{/if}

    <form class="stack" onsubmit={createTarget}>
      <label>
        New target name
        <input type="text" required bind:value={newName} />
      </label>
      <label>
        Classes, separated by commas
        <input
          type="text"
          required
          bind:value={newClasses}
          aria-describedby={classProblem === null ? undefined : 'class-problem'}
        />
      </label>
      {#if classProblem !== null}
        <p id="class-problem" class="field-error">{classProblem}</p>
      {/if}
      <button type="submit" class="button button-solid">Create target</button>
    </form>
  {/if}
</section>

<style>
  .recovery {
    display: grid;
    gap: var(--space-2);
    border: 3px solid var(--ink);
    padding: var(--space-3);
    overflow-wrap: anywhere;
  }

  .drop {
    display: grid;
    gap: var(--space-2);
  }
  .drop h3 {
    font-size: var(--step-0);
  }
  .origin {
    flex-direction: row;
    align-items: center;
    gap: 0;
    font-size: var(--step-0);
    font-weight: 700;
    cursor: pointer;
  }
  /* An origin dot with its first stretch of track. */
  .dot {
    flex: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--ink);
  }
  .dot::after {
    content: '';
    display: block;
    width: 2.5rem;
    height: 5px;
    margin: 4.5px 0 0 12px;
    background: var(--ink);
  }
  .origin .dot {
    margin-right: 3.2rem;
  }
  .origin:hover span:last-of-type {
    text-decoration: underline;
    text-underline-offset: 0.2em;
  }
  .origin:focus-within {
    outline: 2px solid var(--ink);
    outline-offset: 4px;
  }
  .stack {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: end;
    min-width: 0;
    gap: var(--space-2) var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px solid var(--line);
  }
  .stack > :global(p) {
    grid-column: 1 / -1;
  }
  .stack:has(input[type='text']) label:first-of-type,
  .stack:has(input[type='text']) .field-error {
    grid-column: 1 / -1;
  }
  .stack fieldset {
    min-width: 0;
    max-width: 100%;
  }
  .target-line {
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .hint {
    overflow-wrap: anywhere;
  }
  .field-error {
    color: var(--ink);
    font-weight: 600;
    font-size: var(--step--1);
  }
  .lede {
    color: var(--ink-2);
    font-size: var(--step-1);
    line-height: 1.4;
  }

  /* On a phone the columns to choose from read as stops on one line, and the
     fields as lines to write on, not a stack of boxes. */
  @media (max-width: 40rem) {
    .stack {
      grid-template-columns: minmax(0, 1fr);
      border-top: 0;
      padding-top: var(--space-4);
    }
    .stack fieldset {
      flex-direction: column;
      align-items: stretch;
      flex-wrap: nowrap;
      margin-left: 6px;
      border-left: 3px solid var(--ink);
    }
    .stack fieldset legend {
      margin: 0 0 var(--space-2) calc(-6px - 3px);
    }
    .stack fieldset label {
      margin: 0;
      border: 0;
      padding: 0.45rem 0 0.45rem var(--space-4);
      background: none;
      color: var(--ink);
    }
    .stack fieldset label::before {
      content: '';
      position: absolute;
      left: -10.5px;
      top: 50%;
      width: 12px;
      height: 12px;
      margin-top: -6px;
      border: 2.5px solid var(--ink);
      border-radius: 50%;
      background: var(--sheet);
    }
    .stack fieldset label:has(:checked) {
      background: none;
      color: var(--ink);
    }
    .stack fieldset label:has(:checked)::before {
      background: var(--ink);
    }
    .stack input[type='text'] {
      border-width: 0 0 2px;
      padding-inline: 0;
    }
  }
</style>
