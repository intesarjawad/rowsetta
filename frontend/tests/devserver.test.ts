import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import configFor from '../vite.config';

const config = configFor({ command: 'serve', mode: 'development' });

const openapi: unknown = JSON.parse(
  readFileSync(new URL('openapi.json', import.meta.url), 'utf8'),
);

function servedPaths(): string[] {
  if (
    typeof openapi !== 'object' ||
    openapi === null ||
    !('paths' in openapi) ||
    typeof openapi.paths !== 'object' ||
    openapi.paths === null
  ) {
    throw new Error('openapi.json: no paths');
  }
  return Object.keys(openapi.paths);
}

const prefixes = Object.keys(config.server?.proxy ?? {});

// Vite proxies a request when its URL starts with one of the keys.
function proxied(url: string): boolean {
  return prefixes.some((prefix) => url.startsWith(prefix));
}

describe('dev server proxy', () => {
  it('forwards every API path the backend serves, with its query', () => {
    const api = servedPaths()
      .filter((path) => path !== '/')
      .map((path) => path.replace(/\{[^/]+\}/g, '7'));

    expect(api.filter((path) => !proxied(path))).toEqual([]);
    expect(proxied('/table?page=0&size=100')).toBe(true);
  });

  it('keeps the page and its modules on the dev server', () => {
    for (const url of [
      '/',
      '/?states=1',
      '/index.html',
      '/src/main.ts',
      '/src/state.svelte.ts',
      '/@vite/client',
      '/node_modules/.vite/deps/svelte.js',
    ]) {
      expect(proxied(url), url).toBe(false);
    }
  });

  it('forwards nothing the backend does not serve', () => {
    const served = servedPaths();

    expect(
      prefixes.filter(
        (prefix) => !served.some((path) => path.startsWith(prefix)),
      ),
    ).toEqual([]);
  });

  it('forwards to the port the end-to-end server listens on', () => {
    expect(new Set(Object.values(config.server?.proxy ?? {}))).toEqual(
      new Set(['http://127.0.0.1:8787']),
    );
  });
});
