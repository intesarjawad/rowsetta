<script lang="ts">
  import { createBackend } from './backend/http';
  import { createBrowserBackend } from './backend/browser';
  import { BROWSER } from './browser/config';
  import { runtimeLoading } from './browser/loading.svelte';
  import LoadPanel from './LoadPanel.svelte';
  import EvalPanel from './EvalPanel.svelte';
  import ExportPanel from './ExportPanel.svelte';
  import KeySheet from './KeySheet.svelte';
  import Interchange from './Interchange.svelte';
  import LeakList from './LeakList.svelte';
  import { Studio } from './state.svelte';
  import TableView from './TableView.svelte';
  import SetupPanel from './SetupPanel.svelte';
  import './styles/base.css';

  const studio = new Studio(BROWSER ? createBrowserBackend() : createBackend());
  const failure = $derived(
    studio.runtimeFailure ?? studio.workspace?.failure ?? null,
  );
  const workspace = $derived(studio.workspace);
  const loaded = $derived(workspace?.loaded ?? false);
  const refitting = $derived(studio.refitting);
  // Fixed states for design review exist only in the dev server.
  const fixture =
    import.meta.env.DEV && typeof location !== 'undefined'
      ? new URLSearchParams(location.search).get('state')
      : null;

  $effect(() => {
    if (fixture !== null) {
      void import('./fixtures').then((module) => {
        module.applyFixture(studio, fixture);
      });
      return;
    }
    return studio.start();
  });
</script>

<header class="appbar">
  <h1 class="wordmark">Rowsetta</h1>
  {#if BROWSER}<span class="runtime-name" title={runtimeLoading.model}
      ><span class="runtime-full">{runtimeLoading.model}</span><span
        class="runtime-short"
        >{runtimeLoading.fullModel ? 'WebGPU' : 'Browser'}</span
      ></span
    >{/if}
  {#if workspace !== null && loaded}
    <p class="facts">
      <span class="file"
        >{workspace.file_name ?? studio.fileName ?? 'loaded table'}</span
      >
      {#if workspace.target !== null}
        <span class="target">target: {workspace.target}</span>
      {/if}
      {#if studio.rowCount !== null}
        <span class="quiet">{studio.rowCount} rows</span>
      {/if}
      {#if workspace.target !== null}
        <span class="state quiet" class:state--busy={refitting}>
          model {failure !== null
            ? 'failed'
            : refitting
              ? 'updating'
              : 'up to date'}
        </span>
      {/if}
    </p>
  {:else}
    <p class="facts"></p>
  {/if}
  {#if workspace !== null}
    <button
      type="button"
      class="pill-button"
      aria-keyshortcuts="?"
      onclick={() => {
        studio.keySheetOpen = true;
      }}
    >
      <span class="pill-long">Shortcuts</span><kbd class="pill-key">?</kbd>
    </button>
  {/if}
</header>

<main class="shell" class:shell--bare={workspace !== null && !loaded}>
  {#if BROWSER}<LoadPanel failed={failure !== null} />{/if}
  {#if failure !== null}
    <div role="alert" class="alert">
      <p class="what">{failure.error}</p>
      <p class="next">
        {failure.next_step.includes('Save session')
          ? 'Choose another export format. Saved browser labels can be restored after reopening the same CSV and target.'
          : failure.next_step}
      </p>
      <button
        type="button"
        class="button"
        onclick={() => {
          location.reload();
        }}>Retry by reloading</button
      >
    </div>
  {/if}
  {#if studio.problem !== null}
    <div role="alert" class="alert">
      <p class="what">{studio.problem.error}</p>
      <p class="next">{studio.problem.next_step}</p>
    </div>
  {/if}
  {#if studio.connection === 'reconnecting'}
    <div role="status" class="alert">
      <p>Connection lost. Reconnecting to the local server.</p>
      <button
        type="button"
        class="button"
        onclick={() => {
          location.reload();
        }}>Retry now</button
      >
    </div>
  {/if}
  {#if workspace === null}
    <div class="stage">
      {#if failure === null && studio.connection !== 'reconnecting'}<progress
          class="runner"
          aria-label="Connecting"
        ></progress>
        <p>
          {BROWSER
            ? 'Loading the bundled table.'
            : 'Connecting to the local server.'}
        </p>{/if}
    </div>
  {:else}
    <SetupPanel {studio} />
    {#key studio.tableContext}
      {#if loaded && workspace.target !== null}
        <Interchange {studio} />
      {/if}
      {#if loaded}
        <!-- Above the table in reading order, so a filter that shortens the table
      never moves a line under a resting pointer and changes the filter again. -->
        <ExportPanel {studio} />
        <TableView {studio} />
        <EvalPanel {studio} />
        <LeakList {studio} />
      {/if}
    {/key}
    <KeySheet {studio} />
  {/if}
  <p role="status" class="visually-hidden">
    {#key studio.announcement}{studio.announcement?.text ?? ''}{/key}
  </p>
</main>
