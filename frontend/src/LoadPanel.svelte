<script lang="ts">
  let { failed = false }: { failed?: boolean } = $props();
  import { runtimeLoading } from './browser/loading.svelte';
</script>

<aside class="panel" aria-label="Browser runtime">
  <p>
    Nothing leaves this page.
    {#if runtimeLoading.fullModel}TabICLv2 downloads about 56 MB of model
      weights.
    {:else if runtimeLoading.model !== 'Checking WebGPU support'}TabICLv2 needs
      Chromium with WebGPU. The lite model needs no model-weight download.{/if}
  </p>
  {#if failed}
    <p>
      Browser runtime failed. Reload to retry; reopen the same CSV and target to
      restore saved labels.
    </p>
  {:else if !runtimeLoading.ready}
    <label>
      Runtime: {runtimeLoading.done.toLocaleString()} / {runtimeLoading.total.toLocaleString()}
      bytes
      <progress max={runtimeLoading.total || 1} value={runtimeLoading.done}
      ></progress>
    </label>
    {#if runtimeLoading.fullModel}
      <label
        >Model: {runtimeLoading.modelDone.toLocaleString()} / {runtimeLoading.modelTotal.toLocaleString()}
        bytes
        <progress
          max={runtimeLoading.modelTotal || 1}
          value={runtimeLoading.modelDone}
        ></progress>
      </label>
    {/if}
    <p>Label rows now; your labels are kept while the runtime loads.</p>
  {:else}
    <p>Browser runtime ready.</p>
  {/if}
</aside>
