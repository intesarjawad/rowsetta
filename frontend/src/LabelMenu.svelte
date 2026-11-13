<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { optionAfter, tableCommand } from './labelling';

  interface Props {
    id: string;
    rowId: number;
    classes: readonly string[];
    /** The row's human label, which the menu can clear. */
    current: string | null;
    onpick: (label: string | null) => void;
    /** Escape: the opener takes focus back. */
    oncancel: () => void;
    /** Focus moved elsewhere. */
    onleave: () => void;
  }

  let { id, rowId, classes, current, onpick, oncancel, onleave }: Props =
    $props();

  interface Option {
    label: string | null;
    text: string;
  }

  const options: Option[] = $derived([
    ...classes.map((label) => ({ label, text: label })),
    ...(current === null ? [] : [{ label: null, text: 'Clear label' }]),
  ]);

  let active = $state(0);
  let list: HTMLUListElement | undefined;

  onMount(() => {
    active = Math.max(current === null ? 0 : classes.indexOf(current), 0);
    list?.focus();
  });

  $effect(() => {
    const index = active;
    void tick().then(() => {
      list
        ?.querySelector(`[data-index="${String(index)}"]`)
        ?.scrollIntoView({ block: 'nearest' });
    });
  });

  function pick(index: number): void {
    const option = options[index];
    if (option !== undefined) onpick(option.label);
  }

  function onkeydown(event: KeyboardEvent): void {
    const moved = optionAfter(active, event.key, options.length);
    const command = tableCommand(event);
    if (moved !== null) {
      active = moved;
    } else if (event.key === 'Enter' || event.key === ' ') {
      pick(active);
    } else if (event.key === 'Escape') {
      oncancel();
    } else if (
      command?.kind === 'label' &&
      command.classIndex < classes.length
    ) {
      pick(command.classIndex);
    } else {
      return;
    }
    event.preventDefault();
  }

  // Keys reach the listbox, which owns focus, so clicks are handled there too.
  function onclick(event: MouseEvent): void {
    const option =
      event.target instanceof HTMLElement
        ? event.target.closest<HTMLElement>('[role="option"]')
        : null;
    if (option?.dataset.index !== undefined) pick(Number(option.dataset.index));
  }

  function onfocusout(event: FocusEvent): void {
    if (!(
      event.relatedTarget instanceof Node && list?.contains(event.relatedTarget)
    )) {
      onleave();
    }
  }
</script>

<ul
  bind:this={list}
  {id}
  role="listbox"
  tabindex="0"
  aria-label={`Label for row ${String(rowId)}`}
  aria-activedescendant={`${id}-${String(active)}`}
  {onkeydown}
  {onfocusout}
  {onclick}
>
  {#each options as option, index (index)}
    <li
      id={`${id}-${String(index)}`}
      role="option"
      aria-selected={index === active}
      data-index={index}
    >
      {option.text}
    </li>
  {/each}
</ul>

<style>
  li[aria-selected='true'] {
    background: var(--ink);
    color: var(--on-ink);
    outline: 2px solid var(--ink);
    outline-offset: -2px;
    font-weight: 700;
  }
</style>
