import { svelte } from '@sveltejs/vite-plugin-svelte';
import { readFileSync } from 'node:fs';
import { defineConfig } from 'vitest/config';

// The local server, as `rowsetta demo --port 8787` starts it.
const BACKEND = 'http://127.0.0.1:8787';

// The backend serves its API beside the page at the root, so the dev server
// forwards each API path and keeps `/` and its own module paths.
const API_PATHS = [
  '/audit',
  '/columns',
  '/distill',
  '/eval',
  '/events',
  '/export',
  '/health',
  '/labels',
  '/session',
  '/state',
  '/suspects',
  '/table',
  '/target',
  '/threshold',
  '/undo',
];

export default defineConfig(({ mode, command }) => ({
  plugins: [
    svelte(),
    {
      name: 'browser-csp',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'favicon.svg',
          source: readFileSync(
            new URL('./public/favicon.svg', import.meta.url),
          ),
        });
      },
      transformIndexHtml: () =>
        mode === 'browser'
          ? [
              {
                tag: 'meta',
                attrs: {
                  'http-equiv': 'Content-Security-Policy',
                  content:
                    "default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://cdn.jsdelivr.net; worker-src 'self' blob:; img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'none'",
                },
                injectTo: 'head-prepend',
              },
            ]
          : [],
    },
  ],
  // The Python package serves this directory; the wheel build packs it.
  base: mode === 'browser' ? './' : '/',
  publicDir: command === 'serve' ? 'public' : false,
  build: {
    outDir: mode === 'browser' ? '../site' : '../src/rowsetta/static',
    emptyOutDir: true,
  },
  worker: { format: 'es' },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(API_PATHS.map((path) => [path, BACKEND])),
  },
  test: { environment: 'node', include: ['tests/**/*.test.ts'] },
}));
