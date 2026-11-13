import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { LINE_COLOURS } from '../src/palette';

const TOKENS = readFileSync(
  new URL('../src/styles/tokens.css', import.meta.url),
  'utf8',
);

function colour(name: string): number[] {
  const literal = /^#([0-9a-f]{6})$/i.exec(name);
  const match =
    literal ?? new RegExp(`--${name}:\\s*#([0-9a-f]{6})`, 'i').exec(TOKENS);
  if (match?.[1] === undefined) throw new Error(`Token --${name} is missing.`);
  const hex = match[1];
  return [0, 2, 4].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
}

function luminance(name: string): number {
  const [red = 0, green = 0, blue = 0] = colour(name).map((channel) =>
    channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(foreground: string, background: string): number {
  const [light = 0, dark = 0] = [
    luminance(foreground),
    luminance(background),
  ].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

/** WCAG 2.2 AA: 4.5:1 for text, 3:1 for the edges of controls and focus rings. */
const TEXT_PAIRS: readonly (readonly [string, string])[] = [
  ['ink', 'ground'],
  ['ink', 'sheet'],
  ['ink-2', 'ground'],
  ['ink-2', 'sheet'],
  ['ink-3', 'ground'],
  ['ink-3', 'sheet'],
  ['on-ink', 'ink'],
  ['on-ink-quiet', 'ink'],
];
const EDGE_PAIRS: readonly (readonly [string, string])[] = [
  ['edge', 'sheet'],
  ['edge', 'ground'],
  ['ink', 'sheet'],
];

describe('colour tokens', () => {
  it.each(TEXT_PAIRS)('keeps %s readable on %s', (foreground, background) => {
    expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(EDGE_PAIRS)('keeps the %s edge visible on %s', (edge, background) => {
    expect(contrast(edge, background)).toBeGreaterThanOrEqual(3);
  });

  it.each(LINE_COLOURS)('carries white roundel letters on line %s', (line) => {
    expect(contrast('#ffffff', line)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(LINE_COLOURS)('keeps line %s visible on the sheet', (line) => {
    expect(contrast(line, 'sheet')).toBeGreaterThanOrEqual(3);
  });

  it('keeps the ground light and cool', () => {
    expect(luminance('ground')).toBeGreaterThan(0.5);
    const [red = 0, , blue = 0] = colour('ground');
    expect(blue).toBeGreaterThanOrEqual(red);
  });
});
