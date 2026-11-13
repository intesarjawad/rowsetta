import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib
from dataclasses import replace
from time import perf_counter

import numpy as np
from pydantic import BaseModel, JsonValue

from rowsetta.core.leaks import MIN_HUMAN_LABELS, find_leaks
from rowsetta.core.table import ColumnInfo
from scripts.bench_active import Acquisition, acquire
from scripts.bench_common import (
    atomic_json,
    band,
    checkpoint_path,
    dataset,
    load_checkpoint,
    matrix,
    parser,
    provenance,
    publish,
    session,
)

FLIP_RATES = (0.0, 0.05, 0.1, 0.2, 0.4)
LABEL_COUNTS = (30, 50, 100)


class LeakCell(BaseModel):
    """Detection and clean-column measurements for one completed injection."""

    dataset: str
    budget: int
    seed: int
    flip_rate: float
    detected: bool
    clean_columns_flagged: list[str]
    clean_columns: int
    duration_score: float | None
    duration_flagged: bool | None
    wall_seconds: float


def measure(name: str, budget: int, seed: int, flip_rate: float) -> LeakCell:
    """Use a neutral injected column name so detection cannot succeed by name alone."""
    start = perf_counter()
    table, store = session(name, seed)
    uniform = np.full((len(table.frame), len(store.classes)), 1 / len(store.classes))
    acquire(table, store, uniform, budget - len(store.human), Acquisition(seed, "tree", "random"))
    clean = find_leaks(table, store)
    frame = table.frame.copy()
    rng = np.random.default_rng(seed)
    labels = [
        (
            str(rng.choice([label for label in store.classes if label != value]))
            if rng.random() < flip_rate
            else value
        )
        for value in frame[store.target].astype(str)
    ]
    frame["leak"] = labels
    injected = replace(
        table,
        frame=frame,
        columns=(
            *table.columns,
            ColumnInfo("leak", "categorical", len(store.classes) / len(frame), 0),
        ),
    )
    hints = find_leaks(injected, store)
    duration_score: float | None = None
    if name == "bank":
        rows = list(store.human)
        values = frame.loc[rows, ["duration"]]
        duration_score = float(
            importlib.import_module("sklearn.model_selection")
            .cross_val_score(
                importlib.import_module("sklearn.tree").DecisionTreeClassifier(
                    max_depth=1, random_state=7
                ),
                values,
                [store.human[row] for row in rows],
                cv=5,
                scoring="balanced_accuracy",
            )
            .mean()
        )
    return LeakCell(
        dataset=name,
        budget=budget,
        seed=seed,
        flip_rate=flip_rate,
        detected=any(hint.column == "leak" and hint.kind == "single-column" for hint in hints),
        clean_columns_flagged=sorted({hint.column for hint in clean}),
        clean_columns=len(table.columns) - 1,
        duration_score=duration_score,
        duration_flagged=any(hint.column == "duration" for hint in clean)
        if name == "bank"
        else None,
        wall_seconds=perf_counter() - start,
    )


def summaries(results: list[dict[str, JsonValue]]) -> list[JsonValue]:
    """Aggregate detection and clean-column false positives at each strength."""
    groups: dict[tuple[str, int, float], list[LeakCell]] = {}
    for result in results:
        cell = LeakCell.model_validate(result)
        groups.setdefault((cell.dataset, cell.budget, cell.flip_rate), []).append(cell)
    return [
        {
            "dataset": name,
            "budget": budget,
            "flip_rate": rate,
            "seeds": len(group),
            "detection_rate": band([float(cell.detected) for cell in group]),
            "clean_column_false_positive_rate": band(
                [len(cell.clean_columns_flagged) / cell.clean_columns for cell in group]
            ),
        }
        for (name, budget, rate), group in sorted(groups.items())
    ]


def main() -> None:
    """Measure injected-leak detection and false positives independently of rule accuracy."""
    cli = parser("Resumable injected-leak benchmark", budgets=LABEL_COUNTS)
    args = cli.parse_args()
    datasets, _, seeds = matrix(args)
    budgets = args.budgets or ([50] if args.smoke else list(LABEL_COUNTS))
    if any(budget < MIN_HUMAN_LABELS for budget in budgets):
        cli.error("Leak detection requires at least 30 human labels")
    start = perf_counter()
    section = provenance(
        "scripts/bench_leaks.py",
        0,
        {
            "smoke": args.smoke,
            "datasets": datasets,
            "budgets": budgets,
            "seeds": seeds,
            "flip_rates": list(FLIP_RATES),
        },
    )
    for name in datasets:
        source_hash = dataset(name)[1].sha256
        for budget in budgets:
            for seed in seeds:
                for rate in FLIP_RATES:
                    path = checkpoint_path(
                        "leaks",
                        {
                            "dataset": name,
                            "source_sha256": source_hash,
                            "budget": budget,
                            "seed": seed,
                            "flip_rate": rate,
                        },
                    )
                    cell = load_checkpoint(path, LeakCell)
                    if cell is None:
                        cell = measure(name, budget, seed, rate)
                        atomic_json(path, cell.model_dump(mode="json"))
                    section.results.append(cell.model_dump(mode="json"))
                    section.wall_seconds = perf_counter() - start
                    publish("leaks", section, summaries=summaries(section.results))

    print(f"leaks complete cells={len(section.results)} wall_seconds={perf_counter() - start:.3f}")


if __name__ == "__main__":
    main()
