# 0003: Ship TabICLv2 on supported WebGPU browsers

Status: accepted, measured locally on 2026-11-11.

## Decision

The browser ships the four-estimator TabICLv2 teacher on Chromium with a
WebGPU adapter. It uses seed 7, the existing verified fp16-weight graph, and
prediction chunks of at most 500 rows. The lite random forest remains the
fallback when the supported WebGPU runtime is unavailable. Python's teacher,
checkpoint, estimator count and public benchmark results are unchanged.
Weights are staged and verified locally; nothing was uploaded.

## Root cause and tensor bisect

The original spike compared different ensembles. `forecast-web` 1.0.0 hard-coded
seed 42, while Rowsetta's native teacher uses seed 7. The first divergence is
**ensemble construction**, before neural inference. Raw inputs and encoded
training tensors match exactly, including categorical encoding and imputation.
With seed 42, the feature permutations and remapped training-label tensors differ.
The retained [tensor evidence](../browser-evidence/parity-tensors.json) includes
both first-member configurations and the coordinate/values of the largest error.
The narrow pnpm patch exposes `randomState`; the browser explicitly supplies 7.

With identical ensembles, the fp32 network inputs agree exactly for the `none`
normalizer and within 2.3842e-7 for `power`. Temperature (0.9), mean-logit
aggregation, class-column alignment and the training context are unchanged.
Seed alignment alone passes penguins (0.000508), but leaves bank at 0.003337.
That remaining bank error occurs only at test row 1999 with a full 2,000-row
prediction call; fp32 weights still give 0.003180, excluding weight rounding as
its cause.

The second divergence is **WebGPU column-attention block 0**, at the final
row/feature vector in a `[2, 2050, 15]` input (two members, 50 context rows).
An observation-only fp32 graph exposes that vector after the input projection,
each column block and row interaction. Against ONNX Runtime 1.31.1 CPU on the
exact same input:

| Stage, bank power group | Maximum absolute tensor difference |
| --- | --- |
| Input projection | 0 |
| Column-attention block 0 | 0.00217548 |
| Column-attention block 1 | 0.09184089 |
| Column-attention block 2 | 0.15755320 |
| Row representation | 0.12986074 |

The same fp32 ONNX graph on CPU agrees with native real-feature column embeddings
within 5.5e-5 and row representations within 5.3e-5. Reserved CLS slots are
excluded from that column comparison because row interaction replaces them in
place. Thus the remaining fault is the large-shape WebGPU execution path, not
Python preprocessing or the export's mathematical definition. This bisect locates
the first failing model block; it does not identify a particular backend shader.
The 500-row bound avoids the failing shape without changing context rows or the
ensemble. Each query row attends to the same training context.

## Passing deployment evidence

Headed Brave/Chromium on Apple M5, with both `requestAdapter()` and the model's
`webgpu` backend asserted. Four estimators, seed 7, fp16 weights:

| Dataset | Max probability error | Stable-margin flips | Median refit + predict |
| --- | --- | --- | --- |
| penguins | 0.000508 | 0 | 0.2169 s |
| bank_2k | 0.001682 | 0 | 1.8289 s |
| adult_2k | 0.001328 | 0 | not timed |

All rows pass the 0.002 bar; stable-margin flips are zero above a 0.004 native
margin. Near ties are counted separately. Penguins and bank pass their respective
3 s and 10 s latency budgets under concurrent machine load. Full samples are in
[parity-fixed-4.json](../browser-evidence/parity-fixed-4.json). These are local
acceptance measurements, not replacements for public benchmarks.

## Historical no-go evidence

Machine: Apple M5, 32 GiB RAM. Headed Chromium through the installed Brave
executable, with `navigator.gpu.requestAdapter()` asserted before model loading
and `model.backend === 'webgpu'` asserted afterward. Other jobs were running on
the machine, so these latency figures are observations under that load.

`forecast-web` 1.0.0 and ONNX Runtime Web 1.31.1 use fp16 weights from upstream
revision `098fb7be8df8a853a9d7f54a344ee9c6734a53d1`. The staging script verifies
the graph and external weights against the reviewed SHA-256 pins in ADR 0009
on both download and cached reads. Python uses tabicl 2.2.0, seed 7 and the
pinned native checkpoint. `teacher_frame` supplies both paths' identical inputs.
Probability columns are aligned by class name before comparison.

| Estimators | Dataset | Max absolute difference | Stable-margin class flips | Near ties |
| --- | --- | --- | --- | --- |
| 4 | penguins | 0.216487 | 3 | 1 |
| 4 | bank_2k | 0.591745 | 149 | 5 |
| 4 | adult_2k | 0.286585 | 81 | 7 |
| 8 | penguins | 0.124360 | 2 | 0 |
| 8 | bank_2k | 0.506147 | 1406 | 3 |
| 8 | adult_2k | 0.504155 | 1283 | 3 |

The probability gate is max difference <= 0.002 on every row. Stable-margin
flips must be zero where Python's top-two margin exceeds 0.004; near ties are
counted separately. Both gates fail at both estimator counts. These original results established the no-go that the tensor bisect above supersedes.

Latency is refit plus prediction of the whole working table, median of five
runs after one warm-up, with 20 human labels for penguins and 50 for bank_2k.
All timing budgets pass; passing latency does not override failed parity.

| Estimators | Penguins, budget 3.0 s | bank_2k, budget 10.0 s |
| --- | --- | --- |
| 4 | 0.4028 s | 3.1846 s |
| 8 | 0.6834 s | 5.2866 s |

The full five-run samples are retained in
[spike-4.json](../browser-evidence/spike-4.json) and
[spike-8.json](../browser-evidence/spike-8.json).

## Reproduce without a mirror

```sh
uv run python scripts/mirror_onnx.py --local frontend/public/spike/weights --fp32
uv run python scripts/make_parity_golden.py --estimators 4 --trace
pnpm --dir frontend exec playwright test --config playwright.parity.config.ts
# For the tensor bisect, keep a Vite dev server running on port 5173:
pnpm --dir frontend dev
# In another terminal:
node scripts/trace_browser_parity.mjs
uv run --with onnx==1.22.0 python scripts/parity_graph.py
node scripts/trace_browser_parity.mjs --graph
uv run --with onnxruntime==1.31.1 python scripts/compare_parity_tensors.py --graph
```

`--trace` records native encoded inputs, permutations, graph inputs and logits.
The browser diagnostic instruments a generated copy of the installed package;
it never changes production code. The fp32 diagnostic graph adds observation
outputs only. All full tensors and diagnostic weights remain in the ignored
`frontend/public/spike/` directory and are not shipped. `PARITY_URL` overrides
the dev server origin. The separate parity Playwright config starts its own
server and fails on any non-finite probability, excess error or stable flip.

`make browser` packages only the verified fp16 weights with the static demo.
See ADR 0007 for runtime selection, the lite fallback and integration checks.
