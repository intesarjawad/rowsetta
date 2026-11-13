import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import App from '../src/App.svelte';

describe('application shell', () => {
  it('names the product and waits for the local server', () => {
    const { body } = render(App);

    expect(body).toContain('Rowsetta');
    expect(body).toContain('Connecting to the local server.');
  });

  it('keeps an empty polite live region ready for announcements', () => {
    const { body } = render(App);

    expect(body).toMatch(/<p role="status"[^>]*>\s*(<!--[^>]*-->\s*)*<\/p>/);
  });
});
