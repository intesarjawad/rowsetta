<script lang="ts">
  import type { Studio } from './state.svelte';
  import TargetPicker from './TargetPicker.svelte';

  let { studio }: { studio: Studio } = $props();
  let openedFor = $state<number | null>(null);
  const complete = $derived(
    studio.workspace?.loaded === true &&
      studio.workspace.target !== null &&
      studio.recovery?.pending == null,
  );
</script>

<details
  class="setup"
  open={!complete || openedFor === studio.tableContext}
  ontoggle={(event) => {
    openedFor = event.currentTarget.open ? studio.tableContext : null;
  }}
>
  <summary>{complete ? 'Change table or target' : 'Table and target'}</summary>
  <TargetPicker {studio} />
</details>

<style>
  .setup {
    grid-area: target;
    min-width: 0;
  }
  .setup > :global(.panel) {
    margin: var(--space-4) var(--gutter) var(--space-5);
  }
  summary {
    padding: var(--space-3) var(--space-5);
    border-bottom: 1px solid var(--line);
    font-weight: 700;
    cursor: pointer;
  }
  summary:focus-visible {
    outline: 2px solid var(--ink);
    outline-offset: -4px;
  }
</style>
