<script lang="ts">
  import type { SVGAttributes } from 'svelte/elements';

  let {
    text,
    maxWidth,
    ...attributes
  }: SVGAttributes<SVGTextElement> & { text: string; maxWidth: number } =
    $props();
  let node = $state<SVGTextElement>();
  let shown = $state('');

  $effect(() => {
    if (node === undefined) return;
    const font = getComputedStyle(node).font;
    const full = text;
    const width = maxWidth;
    let active = true;
    const fit = (): void => {
      if (!active) return;
      const context = document.createElement('canvas').getContext('2d');
      if (context === null) {
        shown = full;
        return;
      }
      context.font = font;
      if (context.measureText(full).width <= width) {
        shown = full;
        return;
      }
      const letters = Array.from(full);
      let low = 0;
      let high = letters.length;
      while (low < high) {
        const middle = Math.ceil((low + high) / 2);
        if (
          context.measureText(letters.slice(0, middle).join('') + '…').width <=
          width
        )
          low = middle;
        else high = middle - 1;
      }
      shown =
        context.measureText('…').width <= width
          ? letters.slice(0, low).join('') + '…'
          : '';
    };
    fit();
    void document.fonts.ready.then(fit);
    return () => {
      active = false;
    };
  });
</script>

<text {...attributes} bind:this={node}><title>{text}</title>{shown}</text>
