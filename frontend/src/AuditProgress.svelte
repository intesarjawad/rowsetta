<script lang="ts">
  let {
    checking,
    awaiting,
    refit,
  }: {
    checking: boolean;
    awaiting: number | null;
    refit: { done: number; total: number | null } | null;
  } = $props();
</script>

{#if checking}
  <progress class="runner" aria-label="Reading the labels"></progress>
{:else if awaiting !== null}
  <progress
    class="runner"
    aria-label="Fitting the rule again"
    value={refit?.total == null ? undefined : refit.done}
    max={refit?.total ?? undefined}
  ></progress>
{/if}

<style>
  .runner {
    width: 100%;
  }
</style>
