<script lang="ts">
  import {
    evaluationText,
    MIN_EVAL_ROWS,
    percent,
    recallText,
  } from './evaluation';
  import type { Studio } from './state.svelte';
  import { BROWSER } from './browser/config';
  import { runtimeLoading } from './browser/loading.svelte';

  let { studio }: { studio: Studio } = $props();

  // Confidence is a probability, so the slider covers 0 to 1 in 5-point steps.
  const THRESHOLD_STEP = 0.05;

  const workspace = $derived(studio.workspace);
  const evaluation = $derived(workspace?.evaluation ?? null);
  const mode = $derived(studio.mode);
  const unsureCount = $derived(studio.proposals.unsure.size);
</script>

<section class="panel panel--eval" aria-labelledby="eval-heading">
  <h2 id="eval-heading">Teacher accuracy</h2>
  {#if BROWSER}<p class="hint">{runtimeLoading.model}</p>{/if}
  {#if evaluation !== null}
    <p class="peak" aria-hidden="true">{percent(evaluation.accuracy.value)}</p>
  {:else}
    <progress
      aria-label="Evaluation rows labelled"
      max={MIN_EVAL_ROWS}
      value={Math.min(workspace?.eval_count ?? 0, MIN_EVAL_ROWS)}
    ></progress>
  {/if}
  <p class="hint">
    {#if mode.kind === 'label'}
      Evaluation rows are served at random and labelled without seeing a
      proposal.
    {:else if mode.row === null}
      Every row without a human label has been served for evaluation.
    {:else}
      Evaluating row {mode.row}: give it the label you know is right.
    {/if}
  </p>
  <button
    type="button"
    class="button"
    aria-keyshortcuts="e"
    onclick={() => {
      void studio.toggleEvaluation();
    }}
  >
    {mode.kind === 'label' ? 'Evaluate (e)' : 'Stop evaluating (e)'}
  </button>
  {#each evaluationText(evaluation, workspace?.eval_count ?? 0) as sentence (sentence)}
    <p class="sentence">{sentence}</p>
  {/each}
  {#if evaluation !== null}
    <ul class="recall" aria-label="Recall per class">
      {#each Object.entries(evaluation.per_class_recall) as [label, recall] (label)}
        <li>{recallText(label, recall)}</li>
      {/each}
    </ul>
    <p class="hint">
      Raw teacher predictions are measured on all evaluation rows, including
      rows marked unsure. Changing the confidence threshold does not change this
      accuracy.
    </p>
  {/if}

  <h3 class="sub">Unsure proposals</h3>
  <label>
    Confidence threshold
    <input
      type="range"
      min="0"
      max="1"
      step={THRESHOLD_STEP}
      value={workspace?.threshold ?? 0}
      onchange={(event) => {
        void studio.setThreshold(Number(event.currentTarget.value));
      }}
    />
  </label>
  <p class="sentence">
    Threshold {(workspace?.threshold ?? 0).toFixed(2)}: {unsureCount} rows below it
    are marked unsure.
  </p>
</section>

<style>
  .peak {
    font-size: var(--step-peak);
    font-weight: 800;
    line-height: 0.95;
    letter-spacing: -0.04em;
    font-variant-numeric: tabular-nums;
    animation: tick 240ms ease-out both;
  }
  .button {
    align-self: flex-start;
  }
  .sentence {
    overflow-wrap: anywhere;
  }
  .recall {
    display: grid;
    gap: var(--space-1);
    font-family: var(--font-ui);
    font-size: var(--step--1);
    border-top: 1px solid var(--line);
    padding-top: var(--space-2);
  }
  .sub {
    border-top: 1px solid var(--line);
    padding-top: var(--space-3);
  }
  @keyframes tick {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
  }
</style>
