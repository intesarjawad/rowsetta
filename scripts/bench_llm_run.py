import gzip
import json
from statistics import median
from time import perf_counter
from urllib.request import OpenerDirector, ProxyHandler, build_opener

import numpy as np
from pydantic import BaseModel, JsonValue

from scripts.bench_active import Acquisition, run_trajectory, scores
from scripts.bench_common import (
    ROOT,
    Observation,
    atomic_json,
    band,
    checkpoint_path,
    load_checkpoint,
    matrix,
    parser,
    provenance,
    publish,
    session,
)
from scripts.bench_llm import (
    LLM_EVAL_ROWS,
    MODEL_DIGEST,
    REQUEST_TIMEOUT_SECONDS,
    predict_label,
    row_text,
    verify_model,
)

LLM_DATASETS = ("dry_bean", "car", "bank", "penguins", "adult")
MAX_SECONDS = 4 * 60 * 60
AGREEMENT_ROWS = 50
SMOKE_ROWS = 10


class Answer(BaseModel):
    """Cache each completed row and repetition before requesting the next answer."""

    dataset: str
    budget: int
    seed: int
    row: int
    inference_seed: int
    label: str
    seconds: float


def label_rows(
    opener: OpenerDirector, observation: Observation, deadline: float, *, smoke: bool
) -> tuple[list[Answer], dict[str, JsonValue]]:
    """Reuse exactly the random-strategy labels and held-out order from acquisition."""
    table, store = session(observation.dataset, observation.seed)
    columns = [str(column) for column in table.frame.columns if column != store.target]
    train = table.frame.loc[list(observation.human)]
    prefix = (
        "Label the row using the labelled examples. Return JSON with one label.\n"
        f"Columns: {', '.join(columns)}\n"
        + "\n".join(
            f"{row_text(row, columns)}; label={observation.human[list(observation.human)[index]]}"
            for index, (_, row) in enumerate(train.iterrows())
        )
        + "\nRow to label:\n"
    )
    rows = observation.eval_rows[: SMOKE_ROWS if smoke else LLM_EVAL_ROWS]
    answers: list[Answer] = []
    predictions: dict[int, list[str]] = {7: [], 8: []}
    for inference_seed, subset in ((7, rows), (8, rows[:AGREEMENT_ROWS])):
        for row in subset:
            prompt = prefix + row_text(table.frame.loc[[row]].iloc[0], columns)
            path = checkpoint_path(
                "llm",
                {
                    "dataset": observation.dataset,
                    "budget": observation.budget,
                    "seed": observation.seed,
                    "row": row,
                    "inference_seed": inference_seed,
                    "model_digest": MODEL_DIGEST,
                    "prompt": prompt,
                },
            )
            answer = load_checkpoint(path, Answer)
            if answer is None:
                if perf_counter() >= deadline:
                    message = "LLM four-hour compute cap reached; completed row answers are saved."
                    raise SystemExit(message)
                start = perf_counter()
                label = predict_label(
                    opener,
                    prompt,
                    list(store.classes),
                    seed=inference_seed,
                    timeout=min(REQUEST_TIMEOUT_SECONDS, deadline - start),
                )
                answer = Answer(
                    dataset=observation.dataset,
                    budget=observation.budget,
                    seed=observation.seed,
                    row=row,
                    inference_seed=inference_seed,
                    label=label,
                    seconds=perf_counter() - start,
                )
                atomic_json(path, answer.model_dump(mode="json"))
            answers.append(answer)
            predictions[inference_seed].append(answer.label)
    truth = [store.eval[row] for row in rows]
    teacher = np.asarray(observation.proba)[[list(table.frame.index).index(row) for row in rows]]
    repeated = len(predictions[8])
    return answers, {
        "dataset": observation.dataset,
        "budget": observation.budget,
        "seed": observation.seed,
        "llm": scores(truth, predictions[7]),
        "teacher": scores(
            truth, [store.classes[int(teacher[i].argmax())] for i in range(len(rows))]
        ),
        "median_seconds_per_row": median(answer.seconds for answer in answers),
        "seconds": sum(answer.seconds for answer in answers),
        "run_agreement": sum(
            a == b for a, b in zip(predictions[7][:repeated], predictions[8], strict=True)
        )
        / repeated,
        "repeated_rows": repeated,
        "caveat": "may be memorised: famous public dataset"
        if observation.dataset in ("penguins", "adult")
        else "public dataset; training-data exclusion is not established",
    }


def summaries(results: list[dict[str, JsonValue]]) -> list[JsonValue]:
    """Compare LLM and teacher on identical rows with seed bootstrap bands."""
    groups: dict[tuple[str, str], list[dict[str, JsonValue]]] = {}
    for result in results:
        groups.setdefault((str(result["dataset"]), str(result["budget"])), []).append(result)
    output: list[JsonValue] = []
    for (dataset, budget), group in sorted(groups.items()):
        entry: dict[str, JsonValue] = {
            "dataset": dataset,
            "budget": budget,
            "seeds": len(group),
            "caveat": group[0]["caveat"],
        }
        for model in ("llm", "teacher"):
            for metric in ("accuracy", "balanced_accuracy"):
                values: list[float] = []
                for result in group:
                    scores = result[model]
                    if isinstance(scores, dict) and isinstance(
                        value := scores[metric], (int, float)
                    ):
                        values.append(float(value))
                entry[model + "_" + metric] = band(values)
        for metric in ("median_seconds_per_row", "run_agreement"):
            values = [
                float(value) for row in group if isinstance(value := row[metric], (int, float))
            ]
            entry[metric] = band(values)
        output.append(entry)
    return output


def run() -> None:
    """Keep local-model work serial and enforce a resumable four-hour request budget."""
    args = parser("Cached local-LLM benchmark").parse_args()
    datasets, budgets, seeds = matrix(args)
    if not args.datasets and not args.smoke:
        datasets = list(LLM_DATASETS)
    if not args.budgets and not args.smoke:
        budgets = [20, 50]
    if not args.seeds and not args.smoke:
        seeds = seeds[:3]
    opener = build_opener(ProxyHandler({}))
    verify_model(opener)
    start = perf_counter()
    section = provenance(
        "scripts/bench_llm.py",
        0,
        {
            "smoke": args.smoke,
            "datasets": datasets,
            "budgets": budgets,
            "seeds": seeds,
            "model_digest": MODEL_DIGEST,
            "eval_rows": SMOKE_ROWS if args.smoke else LLM_EVAL_ROWS,
        },
    )
    answers: list[Answer] = []
    for name in datasets:
        for seed in seeds:
            for observation in run_trajectory(name, budgets, Acquisition(seed, "tabicl", "random")):
                rows, result = label_rows(
                    opener, observation, start + MAX_SECONDS, smoke=args.smoke
                )
                answers.extend(rows)
                section.results.append(result)
                section.wall_seconds = perf_counter() - start
                publish("llm", section, summaries=summaries(section.results))
                text = "".join(
                    json.dumps(answer.model_dump(mode="json"), sort_keys=True) + "\n"
                    for answer in answers
                )
                destination = ROOT / "docs/bench-data/llm_answers.jsonl.gz"
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".gz.part")
                temporary.write_bytes(gzip.compress(text.encode(), mtime=0))
                temporary.replace(destination)
                print(
                    f"llm {name} budget={observation.budget} seed={seed} rows={len(rows)}",
                    flush=True,
                )
    print(f"llm complete cells={len(section.results)} wall_seconds={perf_counter() - start:.3f}")
