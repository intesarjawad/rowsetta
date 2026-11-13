# 0011: Local LLM labeller baseline

Status: accepted. The local model and the ten-row smoke are verified; the full
run is the last phase of `make bench-full`.

## Model and local runtime

The baseline is Ollama serving `qwen3.6:35b-a3b`, with no paid service,
account or user-data upload. Ollama 0.40.14 was installed and its local API
reported the same version on 2026-11-05. `ollama pull qwen3.6:35b-a3b` was run;
the published artifact is about 23 GB.

The pull exited 0 with `writing manifest` and `success`. `ollama list` reports
ID `0ce5ff81f9ff`. `/api/tags` reports the full manifest digest:

```text
0ce5ff81f9ffdf89dd8192ca7b5d34cefd8996a875b3aaaaafaf5c4813569eba
```

`scripts/bench_llm.py` pins that complete digest and refuses a different local
artifact before requesting labels. `ollama show ... --modelfile` also exited 0.
`ollama show ... --license` returned the Apache License, Version 2.0 text.
During inference, `ollama ps` reported the MLX runner, 100% GPU, 23 GB and a
32,768-token context. No other model was loaded before this smoke. The hardware
model was not recorded.

The [Ollama model page](https://ollama.com/library/qwen3.6:35b-a3b) and
[Qwen's model licence](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/blob/main/LICENSE)
state Apache-2.0, checked on 2026-11-05. Ollama is MIT licensed. The already
installed `qwen3.6-heretic:35b-a3b` was not substituted for the specified model.

## Smoke protocol

`scripts/bench_llm.py --smoke` uses `urllib.request` against
`http://127.0.0.1:11434/api/chat`. It disables proxy routing and sends only the
bundled public penguins fixture. `/api/tags` supplies the full local model
manifest digest before any labels are requested.

The request uses `think: false`, temperature 0, seed 7, `stream: false`, and a
JSON schema whose `label` field is restricted to the training class names.
Responses must be completed, contain exactly the label field, and name a known
class; malformed responses fail the run rather than becoming missing labels.
The prompt lists the column names and 20 labelled rows as
`col=value; ...; label=<class>`, followed by the held-out row. The labelled
prefix is identical for every request, allowing Ollama's prompt-cache reuse.

Both smoke scripts use `scripts/bench_smoke.py`: complete penguins rows shuffled
with seed 7, the first 20 for labels, and the next 10 for evaluation. No
evaluation species enters a prompt. No row-answer cache is read during smoke.
The reported arithmetic mean includes the first request's model load and
prompt evaluation. The median and each row's client wall time are also printed.
There is no separate warm-up, retry, parallel inference or timing subtraction.

The full run must reuse the
random-strategy label sets and held-out rows from `bench_active.py`, run all
required datasets/budgets/seeds, cache row answers, and compare accuracy and
balanced accuracy on identical rows. It must use this ADR's verified model
digest and reproduce the exact prompt and options above.

## Evaluation-row budget

Retain `LLM_EVAL_ROWS = 200` in the script. There are 30 full-benchmark cells:
five datasets, two label budgets and three seeds. Each cell makes 250 requests,
including the 50-row seed-8 agreement rerun, for 7,500 requests overall. Using
the slower observed median of 0.766506 seconds per request, plus the larger
first-row time of 74.485716 seconds again for every cell as a startup/prefix
allowance:

```text
30 * (200 + 50) * 0.766506 + 30 * 74.485716
= 7983.366480 seconds
= 2.217602 hours, below the 14400-second budget
```

The cold-load-inclusive mean is reported separately below; charging that load
on every individual row would repeatedly count model startup. The calculation
above still charges the full first-row time once per cell in addition to all
steady-state requests. This is a planning extrapolation from ten penguins rows,
not a measured full-benchmark duration. Larger prompts and different datasets
may take longer. The full run records its wall time; lower the row count if it
passes the four-hour cap.

## Measured smoke

On 2026-11-05 the first smoke exited 0 and labelled all ten rows. The first
request took 51.533298 seconds, including model startup. The final output was:

```text
rows=10 accuracy=0.900000 seconds_per_row=5.992521 median_seconds_per_row=0.766506 total_seconds=59.925212 LLM_EVAL_ROWS=200
```

These are client wall times around each complete HTTP request. They include
network transport over loopback and response validation. They do not include
the model pull or the inventory query. The 0.90 accuracy is nine correct
answers, not a quality claim based on a ten-row sample.

The final script, including its digest guard, was rerun and exited 0:

```text
rows=10 accuracy=0.900000 seconds_per_row=8.002459 median_seconds_per_row=0.567554 total_seconds=80.024592 LLM_EVAL_ROWS=200
```

Its first request took 74.485716 seconds even with the model already loaded.
The startup/prefix allowance therefore uses this larger observed time, not
only model-loading time. The budget uses the larger median across both runs;
neither slow first request was removed from the printed means.

## Memorisation caveat

Penguins and Adult are famous public datasets and may have appeared in model
training. Their results must carry "may be memorised: famous public dataset".
The smoke accuracy cannot support a general comparison with TabICLv2.
Dry Bean, Car Evaluation and bank are the lead benchmark datasets; no
training-data exclusion is claimed for them either.

## Reproduction

```sh
ollama --version
ollama pull qwen3.6:35b-a3b
ollama show qwen3.6:35b-a3b --modelfile
ollama list
uv run python scripts/bench_llm.py --smoke
```

If the runtime or model is unavailable on a later machine, run those commands
locally after installing Ollama. Do not replace the model,
invent a digest or timing, or treat a missing-model exit as a successful smoke.

## Smoke rerun

A later rerun on 2026-11-05 of the
uncached ten-row smoke exited 0 against the same full manifest digest:

```text
rows=10 accuracy=0.900000 seconds_per_row=1.906769 median_seconds_per_row=0.566979 total_seconds=19.067687 LLM_EVAL_ROWS=200
```

The first request took 13.915337 seconds. Retain the more conservative prior
measurements for the evaluation-row budget; this rerun does not increase it.
