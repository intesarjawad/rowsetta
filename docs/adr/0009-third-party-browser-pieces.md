# 0009: Third-party browser pieces

Status: accepted and implemented. The browser integration uses the vendored
archive, local runtime assets and the pinned weight mirror.
`frontend/src/browser/pyodide.worker.ts` verifies downloaded and cached model bytes before use;
`frontend/e2e-browser/demo.spec.ts` checks the browser network boundary.

Verified on 2026-11-05 against the npm tarball, not a repository checkout.

## Artifact and attribution

`npm pack forecast-web@1.0.0 --ignore-scripts` downloaded the published artifact.
Both the registry metadata at
<https://registry.npmjs.org/forecast-web/1.0.0> and the downloaded bytes match the
published integrity:

```text
sha512-gq0XEdKIEtiBDF902lR1br3bMif0pE9q3NctjTwDqFFEsVd+PHGfzRXymiPtF1Yz0puxuvDWgD87hthgaA5uHg==
SHA-256 e4babb0cb179238a3110e32eec377df6d0032deb16f1441b79c5c3477bc8b499
```

`package.json` declares Apache-2.0 and the archive includes its full LICENSE.
NOTICE credits Vatsal Bakshi (2026), Google Research TimesFM (Apache-2.0),
Amazon Chronos (Apache-2.0), and the Soda team at Inria's TabICL, with the complete
BSD-3-Clause terms. Preserve LICENSE and NOTICE in the vendored archive and
distributions. The archive's ONNX Runtime dependency is `^1.30.0`; the application
lockfile must make that resolution reproducible.

## Network and data review

Read all of `dist/tabular.js`, its imported shared chunks, the session adapter
and the worker entry. This is a static review; no browser network trace was run.

- `tabular.js` preprocesses table rows locally. It passes typed tensors to
  `graph.run`, either in the same context or by `Worker.postMessage` to the
  package's local worker. Neither path sends table contents over HTTP.
- `chunk-SPUU25AM.js` resolves the configured weights base and GETs `config.json`,
  the ONNX graph and, for fp16, its external weights. Its only explicit `fetch`
  call is `fetch(url, { signal })`, with no request body. The default source is
  the pinned Hugging Face repository. Redirect destinations need a browser network
  trace before the Content-Security-Policy is final.
- There are requests beyond weight downloads: `chunk-YLEDJ6OR.js` sets
  `ort.env.wasm.wasmPaths` to
  `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ort.env.versions.web}/dist/`
  unless overridden. ONNX Runtime can load runtime assets there. Bundled worker
  and dynamic module imports also load application assets. Thus the answer to
  "only weight-download requests?" is no.
- No analytics, `XMLHttpRequest`, `WebSocket` or `sendBeacon` call was found in
  the package's shipped JavaScript. ONNX Runtime itself was not audited here,
  so the browser build's network assertion has to cover it.
- `https://forecast-web.invalid/sha256/...` is a Cache Storage key, never passed
  to `fetch` on this code path.

## Integrity limitations

`resolvePin` in `chunk-A6PUF3V3.js` drops embedded file hashes when `weights`
points at a different repository. Mirror loads then obtain hashes from
`config.json`. A mirror must preserve those file entries and use an immutable
revision. `config.json` itself is not checked against an embedded digest.

Fresh graph/weight downloads are SHA-256 checked when hash metadata exists and
Web Crypto is available. Existing Cache Storage hits return before `verify`,
and `verify` returns without checking when `crypto.subtle` is unavailable.
So the package alone does not verify cached weights on read; the browser build
has to check them itself before any page claims that it does.

## Fit and predict limits

`dist/tabular.js:542` exports:

```javascript
Object.freeze({ maxRows: 5000, maxFeatures: 100, maxCells: 20000 });
```

`validate` rejects a fit if any of those caps is exceeded, using the original
input width before constant-column filtering. Test rows have no fixed row cap;
`validateTest` checks their width, and prediction chunks them internally.
A browser fit-limit check is therefore inclusive at 1,250 x 16 and rejects
1,251 x 16. Classification supports at most 10 classes in the reviewed model
metadata. These are library limits, not measured latency or memory guarantees.

## Benchmark source verification

The first download measured these SHA-256 values. They are pinned in
`scripts/fetch_bench_datasets.py`; subsequent reads verify cached bytes too.
Archives are benchmark-only, outside the distributed dataset package.

| Dataset        | Archive bytes | SHA-256                                                            |
| -------------- | ------------- | ------------------------------------------------------------------ |
| Dry Bean       | 4738776       | `0a64eff5be87f48c3dbbfc0a12a56c5d5b5167ef8e61cd45d69b3e7c7130c06f` |
| Mushroom       | 141318        | `face32f32647e0d939f6233f36dd30dd5d619ae9f3f9b8e10bea4ac7e1f60b1a` |
| Car Evaluation | 6342          | `1559d51dcf327f4f8c71b711ceed7fd95a382fc8d8e1998667f4f23b82860403` |

Each UCI page explicitly states CC BY 4.0, checked on 2026-11-05:
[Dry Bean](https://archive.ics.uci.edu/dataset/602/dry+bean+dataset),
[Mushroom](https://archive.ics.uci.edu/dataset/73/mushroom),
[Car Evaluation](https://archive.ics.uci.edu/dataset/19/car+evaluation).
No source was dropped for its licence.

Source citations:

- Dry Bean [Dataset]. (2020). UCI Machine Learning Repository.
  <https://doi.org/10.24432/C50S4B>. Licence: CC BY 4.0.
- Mushroom [Dataset]. (1981). UCI Machine Learning Repository.
  <https://doi.org/10.24432/C5959T>. Licence: CC BY 4.0.
- Bohanec, M. (1988). Car Evaluation [Dataset]. UCI Machine Learning Repository.
  <https://doi.org/10.24432/C5JP48>. Licence: CC BY 4.0.

The fetcher stores the source ZIPs under
`~/.cache/rowsetta/bench/`, or beneath `XDG_CACHE_HOME` when set. It checks
before writing or consuming a cache entry. Both normal mode and `--verify`
download missing archives and verify all three. A mismatch exits nonzero and
leaves the existing file available for inspection and explicit removal.

## Verification commands

```sh
uv run python scripts/fetch_bench_datasets.py --verify
uv run pytest tests/unit/test_cards.py
```

The archive command exited 0 with:

```text
dry_bean: 0a64eff5be87f48c3dbbfc0a12a56c5d5b5167ef8e61cd45d69b3e7c7130c06f (4738776 bytes)
mushroom: face32f32647e0d939f6233f36dd30dd5d619ae9f3f9b8e10bea4ac7e1f60b1a (141318 bytes)
car: 1559d51dcf327f4f8c71b711ceed7fd95a382fc8d8e1998667f4f23b82860403 (6342 bytes)
Verified 3 benchmark archives in /private/tmp/tabular-t03-cache/rowsetta/bench
```

The six card-validation cases passed. An additional temporary corrupt-cache
probe replaced `dry_bean.zip` with invalid bytes in a separate scratch cache.
The fetcher exited 1 with `dataset checksum mismatch: dry_bean` and preserved
those bytes for inspection; no benchmark cache or source archive was changed.

## Vendored archive and install scripts

`frontend/vendor/forecast-web-1.0.0.tgz` contains the unchanged npm archive,
downloaded via `npm pack` with `--ignore-scripts` and independently verified
against the complete SHA-512 integrity above and the recorded SHA-256.
LICENSE and NOTICE remain inside it. The frontend depends on
`file:vendor/forecast-web-1.0.0.tgz`; its pnpm 12.16.1 lockfile records the same
integrity and resolves ONNX Runtime to 1.31.1. No other direct dependency changed.

The transitive `protobufjs@7.6.6` postinstall script only reads package metadata
to check dependency version declarations and optionally prints a warning.
After reviewing that script, `pnpm approve-builds protobufjs --yes` recorded
its explicit permission in `frontend/pnpm-workspace.yaml`. A subsequent
`pnpm --dir frontend install --frozen-lockfile` exited 0. The sandbox used
`--store-dir /private/tmp/tabular-t03-pnpm` for both commands.

`datasets/CARDS.md` now indexes the three benchmark-only archives, records
CC BY 4.0 for each, and links each UCI source and citation. The source licence
statements were rechecked. The card test requires all six datasets
and validates every indexed licence, so omitting a benchmark card fails.

The LLM baseline is recorded in [ADR 0011](0011-llm-labeller-baseline.md).
