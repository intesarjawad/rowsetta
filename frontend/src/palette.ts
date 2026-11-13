import type { Kind } from './transit';

/**
 * Line colours, one per class in the order the server lists them. Each carries
 * white roundel letters at 4.5:1 or more (tests/tokens.contrast.test.ts).
 * Hex rather than tokens, because the lens rasterises the map outside the page's CSS.
 */
export const LINE_COLOURS = [
  '#1f44b8',
  '#c2410c',
  '#0b7a45',
  '#7b2d8e',
  '#6b4f2a',
  '#b0124f',
  '#0f6e80',
  '#4a4f57',
] as const;

/** Rows with no label yet ride in this grey. */
export const NO_LABEL = '#b4b7bc';

export function lineColour(
  classes: readonly string[],
  cls: string | null,
): string {
  if (cls === null) return NO_LABEL;
  const index = classes.indexOf(cls);
  return (
    LINE_COLOURS[(index === -1 ? 0 : index) % LINE_COLOURS.length] ??
    LINE_COLOURS[0]
  );
}

/** A model's proposal rides the same line, paler, so a person's label reads as the stronger claim. */
export function bandColour(
  classes: readonly string[],
  cls: string | null,
  kind: Kind,
): string {
  const colour = lineColour(classes, cls);
  if (kind !== 'proposed') return colour;
  const mix = (at: number): string =>
    Math.round(parseInt(colour.slice(at, at + 2), 16) * 0.45 + 255 * 0.55)
      .toString(16)
      .padStart(2, '0');
  return `#${mix(1)}${mix(3)}${mix(5)}`;
}
