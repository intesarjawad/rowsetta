<script lang="ts">
  import type { Studio } from './state.svelte';

  let { studio }: { studio: Studio } = $props();

  const KEYS: readonly (readonly [string, string])[] = [
    ['1 to 9, 0', 'Label the row with class 1 to 9, or 10'],
    ['j or Down', 'Next row'],
    ['k or Up', 'Previous row'],
    ['Enter', 'Open the label menu'],
    ['n', 'Jump to the next suggested row'],
    ['e', 'Start or stop evaluation'],
    ['u', 'Undo the last label change'],
    ['?', 'Show these keys'],
    ['Escape', 'Close a menu, or show every row after a rule line'],
  ];

  let dialog: HTMLDialogElement | undefined;

  // A modal dialog traps focus, closes on Escape and gives focus back to its opener.
  $effect(() => {
    if (studio.keySheetOpen && dialog?.open === false) dialog.showModal();
  });
</script>

<dialog
  bind:this={dialog}
  aria-labelledby="keys-heading"
  onclose={() => {
    studio.keySheetOpen = false;
  }}
>
  <h2 id="keys-heading">Keyboard</h2>
  <p>These keys work while a label cell has focus.</p>
  <dl>
    {#each KEYS as [key, action] (key)}
      <dt><kbd>{key}</kbd></dt>
      <dd>{action}</dd>
    {/each}
  </dl>
  <form method="dialog">
    <button type="submit" class="button">Close</button>
  </form>
</dialog>
