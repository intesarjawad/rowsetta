# 0001: TabICLv2 as the teacher

Status: accepted.

## Decision

The teacher is TabICLv2 (`tabicl` 2.2.0, checkpoint
`tabicl-classifier-v2-20260212.ckpt` under the BSD 3-Clause licence), run
locally from a revision-pinned, checksum-verified download
(`teachers/checkpoint.py`). It learns in context, with no gradient training, so
the app can refit after every label. TabPFN v2 appears only as a
baseline learner in `scripts/bench_learners.py`.

## Installed API verification

On 2026-11-05, `tabicl` 2.2.0 from the locked environment exposed all constructor
parameters the adapter in `teachers/tabicl.py` passes. The command exited 0:

```sh
uv run python -c "import tabicl, inspect; print(inspect.signature(tabicl.TabICLClassifier))"
```

Relevant fields from the printed signature:

```text
n_estimators: int = 8
kv_cache: bool | str = False
model_path: Optional[str | Path] = None
device: Optional[str | torch.device] = None
checkpoint_version: str = 'tabicl-classifier-v2-20260212.ckpt'
```

This confirms the adapter's planned arguments, not teacher latency, parity or
KV-cache performance. Those remain their own model acceptance checks.

## Optional TabPFN v2 benchmark

The baseline explicitly calls
`TabPFNClassifier.create_default_for_version(ModelVersion.V2)` so that a changed
default cannot silently select a gated model. It imports TabPFN only when the
benchmark is run. The smoke below checks execution; the full comparison runs
TabPFN v2 as the `tabpfn` learner in `scripts/bench_active.py`.

On 2026-11-05 the locked TabPFN 9.2.0 completed local CPU inference without a
token or login. Twenty complete penguins rows supply labels and ten disjoint
rows form the smoke evaluation. Both benchmark smoke scripts use the same
seed-7 split. This smoke is an execution check, not a benchmark estimate.

```sh
env -u TABPFN_TOKEN uv run --group bench python scripts/bench_baseline_tabpfn.py --model v2 --smoke
```

```text
TabPFN v2: labels=20 rows=10 accuracy=1.000000 seconds=8.279573 TABPFN_TOKEN=unset
```

Exit status: 0. No account step is needed for this v2 path. Later model
versions and their access terms were not tested.

The final script was rerun against the now-cached v2 weights, again exiting 0:

```text
TabPFN v2: labels=20 rows=10 accuracy=1.000000 seconds=0.182649 TABPFN_TOKEN=unset
```

These timings have different cache states and are not benchmark comparisons.

The sandbox run relocated the uv, Hugging Face, model, matplotlib and skrub
caches with `UV_CACHE_DIR`, `HF_HOME`, `TABPFN_MODEL_CACHE_DIR`, `MPLCONFIGDIR`
and `SKB_DATA_DIRECTORY`, respectively, to directories beneath `/private/tmp/`.
The initial skrub import failed trying to create `~/skrub_data`; setting its
documented `SKB_DATA_DIRECTORY` resolved that filesystem restriction. No
package versions, credentials, fit inputs or model selection were changed.
