import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

import numpy as np
from numpy.typing import NDArray
from pydantic import JsonValue

from rowsetta.core.active import Predictions, next_row
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table
from scripts.bench_common import (
    BUDGETS,
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
from scripts.bench_learners import LEARNERS, STRATEGIES, probabilities

BATCH_SIZE = 5
NOISE_SEED_OFFSET = 1000
CALIBRATION_BINS = 10


def scores(truth: list[str], predicted: Sequence[str | None]) -> dict[str, JsonValue]:
    """Keep coverage separate from accuracy among answered rows."""
    pairs = [(a, b) for a, b in zip(truth, predicted, strict=True) if b is not None]
    accuracy = sum(a == b for a, b in pairs) / len(pairs) if pairs else None
    recalls = [
        sum(a == b for a, b in pairs if a == label) / sum(a == label for a, _ in pairs)
        for label in sorted(set(truth))
        if any(a == label for a, _ in pairs)
    ]
    return {
        "accuracy": accuracy,
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else None,
        "answered": len(pairs),
        "total": len(truth),
    }


@dataclass(frozen=True)
class Acquisition:
    """Settings shared by every budget on one deterministic acquisition path."""

    seed: int
    learner: str
    strategy: str
    noise: float = 0.0


def settings(
    name: str, budget: int, config: Acquisition, store: LabelStore
) -> dict[str, JsonValue]:
    """Use identical cache keys for standalone scripts and downstream consumers."""
    return {
        "dataset": name,
        "source_sha256": store.source.sha256,
        "rows": len(store.source.row_ids()),
        "budget": budget,
        "threshold": store.threshold,
        "seed": config.seed,
        "learner": config.learner,
        "strategy": config.strategy,
        "oracle_noise": config.noise,
    }


def acquire(
    table: Table, store: LabelStore, proba: NDArray[np.float64], count: int, config: Acquisition
) -> None:
    """Acquire a frozen-probability batch, excluding every held-out row."""
    seed, strategy, noise = config.seed, config.strategy, config.noise
    rows = [int(row) for row in table.frame.index]
    predictions = Predictions(proba, rows, store.classes)
    for _ in range(count):
        pick = len(store.human)
        rng = np.random.default_rng(np.random.SeedSequence([seed, pick]))
        available = [row for row in rows if row not in store.human and row not in store.eval]
        if strategy == "ours":
            row = next_row(predictions, store, pick_index=pick - 2 * len(store.classes), rng=rng)
        elif strategy == "random":
            row = int(rng.choice(available))
        else:
            positions = [rows.index(row) for row in available]
            ordered = np.sort(proba[positions], axis=1)
            row = available[int((ordered[:, -1] - ordered[:, -2]).argmin())]
        label = str(table.frame.loc[row, store.target])
        noise_rng = np.random.default_rng(seed + NOISE_SEED_OFFSET)
        offset = 0
        for _ in range(pick - 2 * len(store.classes) + 1):
            offset = (
                int(noise_rng.integers(1, len(store.classes))) if noise_rng.random() < noise else 0
            )
        label = store.classes[(store.classes.index(label) + offset) % len(store.classes)]
        store.set_human(row, label)
    store.human = dict(sorted(store.human.items()))


def calibration(proba: NDArray[np.float64], truth: list[str], classes: tuple[str, ...]) -> float:
    """Measure calibration error in ten equal-width confidence bins."""
    confidence = proba.max(axis=1)
    correct = np.array([classes[int(proba[i].argmax())] == label for i, label in enumerate(truth)])
    bins = np.minimum((confidence * CALIBRATION_BINS).astype(int), CALIBRATION_BINS - 1)
    return sum(
        (int(np.count_nonzero(bins == index)) / len(truth))
        * abs(float(correct[bins == index].mean()) - float(confidence[bins == index].mean()))
        for index in range(CALIBRATION_BINS)
        if np.any(bins == index)
    )


def run_trajectory(name: str, budgets: list[int], config: Acquisition) -> list[Observation]:
    """Resume completed budgets and write each new cell before beginning the next."""
    seed, learner, strategy, noise = config.seed, config.learner, config.strategy, config.noise
    table, store = session(name, seed)
    store.human = dict(sorted(store.human.items()))
    valid = [budget for budget in budgets if budget >= len(store.human)]
    observations: list[Observation] = []
    for budget in valid:
        path = checkpoint_path("active", settings(name, budget, config, store))
        cached = load_checkpoint(path, Observation)
        if cached is not None:
            store.human = dict(sorted(cached.human.items()))
            observations.append(cached)
            continue
        start = perf_counter()
        proba = probabilities(learner, table, store, seed)
        while len(store.human) < budget:
            acquire(
                table,
                store,
                proba,
                min(
                    BATCH_SIZE,
                    min(boundary for boundary in BUDGETS if boundary > len(store.human))
                    - len(store.human),
                ),
                config,
            )
            proba = probabilities(learner, table, store, seed)
        positions = [list(table.frame.index).index(row) for row in store.eval]
        truth = list(store.eval.values())
        predicted = [store.classes[int(proba[position].argmax())] for position in positions]
        metrics = scores(truth, predicted)
        if learner == "tabicl":
            metrics["ece_10_bins"] = calibration(proba[positions], truth, store.classes)
        observation = Observation(
            dataset=name,
            source_sha256=store.source.sha256,
            budget=budget,
            seed=seed,
            learner=learner,
            strategy=strategy,
            noise=noise,
            human=store.human.copy(),
            eval_rows=list(store.eval),
            classes=store.classes,
            proba=proba.tolist(),
            wall_seconds=perf_counter() - start,
            metrics=metrics,
        )
        atomic_json(path, observation.model_dump(mode="json"))
        print(
            f"active {name} budget={budget} seed={seed} {learner}/{strategy} "
            f"noise={noise} seconds={observation.wall_seconds:.3f}",
            flush=True,
        )
        observations.append(observation)
    return observations


def summaries(observations: list[Observation]) -> list[dict[str, JsonValue]]:
    """Aggregate seed metrics without mixing strategies, budgets or noise arms."""
    groups: dict[tuple[str, int, str, str, float], list[Observation]] = {}
    for observation in observations:
        key = (
            observation.dataset,
            observation.budget,
            observation.learner,
            observation.strategy,
            observation.noise,
        )
        groups.setdefault(key, []).append(observation)
    results: list[dict[str, JsonValue]] = []
    for (dataset, budget, learner, strategy, noise), group in sorted(groups.items()):
        entry: dict[str, JsonValue] = {
            "dataset": dataset,
            "budget": budget,
            "learner": learner,
            "strategy": strategy,
            "noise": noise,
            "seeds": len(group),
        }
        for metric in group[0].metrics:
            values = [
                float(value)
                for item in group
                if isinstance(value := item.metrics[metric], (int, float))
            ]
            if values:
                entry[metric] = band(values)
        results.append(entry)
    return results


def main() -> None:
    """Measure label efficiency using learner-specific acquisition probabilities."""
    cli = parser("Resumable label-efficiency benchmark")
    cli.add_argument("--only", choices=(*LEARNERS, "tree"), nargs="+")
    cli.add_argument("--oracle-noise", type=float, choices=[0.0, 0.1], default=0.0)
    args = cli.parse_args()
    datasets, budgets, seeds = matrix(args)
    learners = args.only or [name for name in LEARNERS if not args.smoke or name != "tabpfn"]
    if args.oracle_noise:
        learners = args.only or ["tabicl", "tree"]
        if any(name not in ("tabicl", "tree") for name in learners):
            cli.error("The noisy arm supports tabicl and tree only")
    start = perf_counter()
    section = provenance(
        "scripts/bench_active.py",
        0,
        {
            "smoke": args.smoke,
            "datasets": datasets,
            "budgets": budgets,
            "seeds": seeds,
            "learners": learners,
            "oracle_noise": args.oracle_noise,
        },
    )
    ineligible: list[JsonValue] = [
        {
            "dataset": dataset,
            "budget": budget,
            "status": "n/a (seed set larger than budget)",
        }
        for dataset in datasets
        for budget in budgets
        if budget < len(session(dataset, seeds[0])[1].human)
    ]
    observations: list[Observation] = []
    for name in datasets:
        for learner in learners:
            for strategy in STRATEGIES if not args.oracle_noise else ("ours", "random"):
                for seed in seeds:
                    observations.extend(
                        run_trajectory(
                            name, budgets, Acquisition(seed, learner, strategy, args.oracle_noise)
                        )
                    )
                    section.results = summaries(observations)
                    section.wall_seconds = perf_counter() - start
                    publish(
                        "active_noise" if args.oracle_noise else "active",
                        section,
                        ineligible_cells=ineligible,
                    )
    print(f"active complete cells={len(observations)} wall_seconds={perf_counter() - start:.3f}")


if __name__ == "__main__":
    main()
