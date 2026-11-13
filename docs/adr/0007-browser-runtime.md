# 0007: A static, self-contained Pyodide and WebGPU demo

Status: implemented; local acceptance on 2026-11-11.

## Teacher and shared core

[ADR 0003](0003-browser-demo.md) supersedes the original parity no-go. The
four-estimator browser TabICLv2 now uses the native seed 7 and 500-row prediction
chunks. Maximum errors are 0.000508 on penguins, 0.001682 on bank and 0.001328 on
adult, below 0.002, with no stable-margin flips. The Python teacher is unchanged.

The full browser path requires Chromium and an actual WebGPU adapter in the
worker. ONNX Runtime's [browser support matrix](https://onnxruntime.ai/docs/get-started/with-javascript/web.html)
does not support its WebGPU provider on Safari or Firefox. This matters in
practice: local WebKit exposed an adapter but never completed the six-label demo
prediction within 240 seconds. Adapter presence alone is not sufficient.
Safari/WebKit, Firefox and Chromium without an adapter use `LiteTeacher`, the
existing seeded 200-tree random forest. The header, evaluation panel, loading
panel and exported certificate identify the teacher actually selected.

The Pyodide worker owns both the in-memory `BrowserShell` and the asynchronous
ONNX session. This keeps tables inside one worker and avoids copying them through
the page or a network service. Runtime and model downloads start concurrently.
The browser shell prepares `teacher_frame` and human-only training labels;
JavaScript fits and predicts locally, then Python validates probability shapes,
classes, finite values, row sums and generation before publishing through the
shared core. Evaluation rows never enter training and remain hidden in the UI.
A stale result cannot publish over a newer workspace generation.

Only the full teacher enforces the reviewed fit limits: 5,000 labelled rows,
100 features and 20,000 labelled cells. The lite path retains its existing
behavior. CSV upload is limited to 50 MB, with the shared seeded 2,000-row cap.
Existing-column prefill and label-audit controls remain local-app features.
DuckDB, torch and FastAPI are neither packaged nor loaded in the browser.
Export execution is still explicitly `NotExecuted("browser demo")`.

## Build, loading and privacy

`make browser` packages the core wheel, Pyodide 314.0.7 and its locked scientific
and Pydantic packages, verified fp16 ONNX weights and ONNX Runtime Web 1.31.1.
The wheel carries checked-hash bytecode compiled by that Pyodide version for
the core and the verified pandas and scikit-learn sources, and export formats
and leak analysis import only when requested.
Everything is served from the same static origin, including the ONNX runtime's
WASM support files. No account, weight mirror, upload or external service is
required. Relative URLs support a repository subpath. Use HTTP(S), not `file://`.

The staging script checks weights against immutable SHA-256 pins on download
and cached reads. A build manifest pins local assets; the worker verifies
Cache Storage hits and fresh downloads. Corrupt cache entries are discarded.
Forecast-web's internal weight cache is disabled because its cache hits bypass
SHA validation. Its fetches instead use the worker's verified cache, followed by
forecast-web's graph and external-weight pin checks. JavaScript module imports
use ordinary browser module caching. The diagnostic fp32 graph and full
tensor captures stay in the ignored spike directory and never enter `site/`.

The shell paints a target-masked penguins table before startup finishes. Early
labels queue in order and only the latest mutation updates the page. The loading
panel reports runtime bytes and, on the full-model path, model bytes separately.
The fp16 model download is about 56 MB. Runtime fetch failure stops the worker,
preserves displayed labels and offers reload recovery.

The CSP permits same-origin scripts/workers/assets and retains the existing
jsDelivr connection allowance; the shipped flow needs only same-origin GETs.
No request carries table data. No Hugging Face host, telemetry or form submission
is needed by the shipped build.

## Verification

The dedicated parity Playwright config runs the actual browser teacher in headed
Chromium, asserts an adapter and `webgpu` backend, and enforces the probability
and stable-margin gates on all three complete tables. Unit regression tests
cover seed forwarding, bounded batches preserving row order, browser-runtime
selection, human-only context, evaluation masking, malformed/stale predictions
and cached diagnostic-weight checksum verification.

The static browser suite exercises queued labels, proposals and SQL export plus
failed-runtime-download recovery in Chromium, Firefox and WebKit. Chromium must
use TabICLv2; unsupported runtimes must use the lite model with no weight fetch.
Every observed request must be a same-origin GET without body or query string.

```sh
make check
make browser
pnpm --dir frontend exec playwright test --config playwright.browser.config.ts
pnpm --dir frontend exec playwright test --config playwright.parity.config.ts
```

The final local run on 2026-11-11 passed `make check` (472 Python tests,
12 deselected, and 207 frontend tests), `make browser`, all six browser
smoke tests and the headed WebGPU parity test. Svelte reported zero errors
and warnings. Chromium and WebKit rendered states were inspected.

## Startup measurement procedure

The existing `cold_start.browser` figures in [bench.json](../bench.json) describe
an earlier lite-only build. They are historical, not current launch figures.
The current launch bar remains 10 seconds to label, 30 seconds to proposals on
the first visit, and 6 seconds to proposals on the second visit.

With a built browser preview running at `http://127.0.0.1:4174/`, run:

```sh
uv run --locked python scripts/cold_start.py --browser http://127.0.0.1:4174/ --browser-runs 5 --browser-path both && uv run --locked python scripts/render_bench.py
```

This waits for one-minute load at or below 8, measures five clean-profile pairs
per path in headed Chromium at 50 Mbit/s and 40 ms, restarts Chromium on the same
profile for each second visit, and asserts the median budgets. It records the
actual teacher, browser identity, served manifest SHA, load averages and asset
transfers. Successful output regenerates [bench.md](../bench.md); individual
runs are saved in `docs/bench-data/browser-startup-runs.json`.

For diagnostics, `scripts/browser_cold_start.mjs --runs 5 --path both
--allow-heavy-load URL OUTPUT` bypasses only the load gate. Its results are
marked **heavy-load diagnostic** and must remain outside the launch timing docs.
