# Development notes

## Registry verification

Checked public PyPI JSON and npm registry metadata on 2026-11-05. Versions below
are the latest stable versions reported by each registry, not benchmark results.
Python packages resolve in `uv.lock`; frontend direct dependencies are exact pins.

| Registry | Package | Latest stable |
| --- | --- | --- |
| PyPI | `uv` | 0.13.7 |
| PyPI | `tabicl` | 2.2.0 |
| PyPI | `torch` | 2.15.0 |
| PyPI | `scikit-learn` | 1.9.1 |
| PyPI | `pandas` | 3.1.1 |
| PyPI | `numpy` | 2.5.4 |
| PyPI | `scipy` | 1.18.1 |
| PyPI | `duckdb` | 2.0.0 |
| PyPI | `psycopg` | 3.3.8 |
| PyPI | `dbt-core` | 1.12.6 |
| PyPI | `dbt-duckdb` | 1.11.1 |
| PyPI | `fastapi` | 0.162.0 |
| PyPI | `uvicorn` | 0.54.0 |
| PyPI | `huggingface-hub` | 2.4.0 |
| PyPI | `hypothesis` | 6.170.14 |
| PyPI | `hatchling` | 1.33.0 |
| PyPI | `fonttools` | 4.68.0 |
| PyPI | `tabpfn` | 9.2.0 |
| PyPI | `orbital` | 0.6.0 |
| PyPI | `ruff` | 0.17.3 |
| PyPI | `pyright` | 1.1.414 |
| PyPI | `pytest` | 9.2.0 |
| PyPI | `httpx` | 0.28.1 |
| PyPI | `pydantic` | 2.14.2 |
| npm | `svelte` | 5.57.3 |
| npm | `vite` | 8.3.6 |
| npm | `typescript` | 7.0.2 |
| npm | `@sveltejs/vite-plugin-svelte` | 7.3.1 |
| npm | `@types/node` (26.x) | 26.6.6 |
| npm | `svelte-check` | 4.7.8 |
| npm | `eslint` | 10.14.0 |
| npm | `typescript-eslint` | 8.72.1 |
| npm | `eslint-plugin-svelte` | 3.24.0 |
| npm | `prettier` | 3.9.10 |
| npm | `prettier-plugin-svelte` | 4.1.1 |
| npm | `markdownlint-cli2` | 0.24.0 |
| npm | `vitest` | 5.1.0 |
| npm | `@playwright/test` | 1.64.1 |
| npm | `@axe-core/playwright` | 4.14.0 |
| npm | `forecast-web` | 1.0.0 |
| npm | `onnxruntime-web` | 1.31.1 |
| npm | `pyodide` | 314.0.7 |
| npm | `pnpm` | 12.16.1 |
| PyPI | `pre-commit` | 4.7.0 |

Sources: `https://pypi.org/pypi/<package>/json` and
`https://registry.npmjs.org/<package>/latest`.

- Updated pandas from 3.1.0 to 3.1.1 and Vite from 8.3.5 to 8.3.6, the newest
  stable releases (engineering standards section 5). Re-confirmed both registry
  versions on
  2026-11-05; `uv.lock` retains pandas 3.1.1 and the frontend retains Vite 8.3.6.
  Pyodide floors remain unchanged.
- Pinned `@types/node` 26.6.6 as a frontend development dependency on
  2026-11-05, the latest stable 26.x release reported by
  `https://registry.npmjs.org/@types%2fnode`, to match Node 26 LTS. Its required
  `undici-types` dependency is transitive. No other direct dependency was added.
  These declarations satisfy the Vite and Vitest Node types without weakening
  TypeScript, Svelte or ESLint checks.
- TypeScript stays at 6.0.3 although 7.0.2 is available: typescript-eslint 8.72.1
  requires a version below 6.1.0.
- Build backend: hatchling 1.33.0. Pre-commit 4.7.0 is included to make setup
  reproducible.
- `pandas-stubs` 3.1.0.261029 is a development dependency for strict pyright;
  its version policy matches pandas major and minor versions, and these stubs
  target pandas 3.1.
- Installed tools reported uv 0.13.7, Node 26.13.0 and gitleaks 8.30.1.
  pnpm 12.16.1 was installed in temporary tooling storage for verification.
- Confirmed torch 2.15.0 in `https://download.pytorch.org/whl/cpu/torch/`.
  The Linux/Windows explicit CPU source is configured before the first lock.
- NOTICE retains the TabICL sdist licence, including its Apache-2.0 forecast
  attribution, and forecast-web 1.0.0's npm NOTICE. forecast-web is vendored as
  `frontend/vendor/forecast-web-1.0.0.tgz` after the source review in ADR 0009.

## Local workflows

- `make setup` installs locked dependencies and builds the local frontend. It
  installs pre-commit hooks only when `core.hooksPath` is unset; an existing hook
  configuration is preserved. Run `make check` before committing in either case.
- `make browser` builds the static demo in `site/`. Chromium with WebGPU uses
  TabICLv2; other browsers use the labelled lite-model fallback. See ADR 0003,
  ADR 0007 and ADR 0009 for the runtime decisions.
- The browser demo saves labels in the browser's local storage. Reopen the same
  CSV and target to restore or discard saved labels. The local app saves labels
  in its session storage; reopening the same CSV restores its session.
- `make demo-gif` records and validates `docs/demo.gif`.
- Release runs on a `v*` tag; Pages and the install smoke run only when
  dispatched or called by the release.
