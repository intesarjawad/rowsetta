<script lang="ts">
  import { BROWSER } from './browser/config';
  let {
    hasSuspects,
    hasShown,
    hasRule,
    checking,
    missingAudit,
    oncheck,
  }: {
    hasSuspects: boolean;
    hasShown: boolean;
    hasRule: boolean;
    checking: boolean;
    missingAudit: [string, number][];
    oncheck: () => Promise<void>;
  } = $props();
</script>

{#if hasSuspects && hasShown}
  <div class="acts">
    <button
      type="button"
      class="button"
      disabled={checking || missingAudit.length > 0}
      onclick={() => {
        void oncheck();
      }}>Check again</button
    >
  </div>
{:else if !BROWSER && hasRule && !checking && !hasSuspects}
  <div class="acts">
    <button
      type="button"
      class="button button-solid"
      disabled={missingAudit.length > 0}
      onclick={() => {
        void oncheck();
      }}>Check the labels</button
    >
  </div>
{/if}
{#if !BROWSER && missingAudit.length > 0}
  <p class="hint">
    Checking labels needs {missingAudit
      .map(([label, count]) => `${String(count)} more ${label}`)
      .join(', ')} human labels (5 per class).
  </p>
{/if}

<style>
  .acts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
