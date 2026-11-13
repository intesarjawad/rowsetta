import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import importlib
from dataclasses import dataclass
from time import perf_counter

import numpy as np

from rowsetta.core.audit import audit_labels
from rowsetta.core.session import LabelStore
from rowsetta.core.teacher import Teacher
from rowsetta.teachers.fake import FakeTeacher
from scripts.bench_common import TARGETS, dataset

FLIP_RATE = 0.05
FLIP_SEED = 7
DATASETS = ("penguins", "bank")


@dataclass(frozen=True)
class AuditResult:
    """Precision at k, where k is the number of flipped labels."""

    dataset: str
    rows: int
    k: int
    hits: int
    precision: float
    p_value: float
    wall_seconds: float


def flip_labels(
    labels: dict[int, str], classes: tuple[str, ...], *, seed: int = FLIP_SEED
) -> tuple[dict[int, str], set[int]]:
    """Flip a seeded share of labels, each to a different class chosen at random."""
    rng = np.random.default_rng(seed)
    rows = sorted(labels)
    chosen = {int(row) for row in rng.choice(rows, round(FLIP_RATE * len(rows)), replace=False)}
    flipped = labels.copy()
    for row in sorted(chosen):
        flipped[row] = str(rng.choice([label for label in classes if label != labels[row]]))
    return flipped, chosen


def measure(name: str, teacher: Teacher) -> AuditResult:
    """Audit a fully labelled bundled dataset after flipping a known set of labels."""
    start = perf_counter()
    table, source = dataset(name)
    target = TARGETS[name]
    answers = table.frame[target].dropna().astype(str)
    classes = tuple(sorted(answers.unique()))
    human, flipped = flip_labels(
        dict(zip(answers.index.to_list(), answers.to_list(), strict=True)), classes
    )
    store = LabelStore(classes=classes, target=target, source=source, human=human)
    ranked = audit_labels(teacher, table, store)
    hits = len({suspect.row_id for suspect in ranked[: len(flipped)]} & flipped)
    # One-sided: a random ranking finds each flipped row with probability FLIP_RATE.
    p_value = float(
        importlib.import_module("scipy.stats")
        .binomtest(hits, len(flipped), FLIP_RATE, alternative="greater")
        .pvalue
    )
    return AuditResult(
        name, len(human), len(flipped), hits, hits / len(flipped), p_value, perf_counter() - start
    )


def make_teacher(name: str) -> Teacher:
    """Load the local model only when it is the teacher being measured."""
    if name == "fake":
        return FakeTeacher()
    return importlib.import_module("rowsetta.teachers.tabicl").TabICLTeacher()


def parser() -> argparse.ArgumentParser:
    """Accept only datasets and teachers this benchmark knows."""
    cli = argparse.ArgumentParser(description="Label audit benchmark: precision at k")
    cli.add_argument("--datasets", nargs="+", choices=DATASETS, default=list(DATASETS))
    cli.add_argument("--teacher", choices=("tabicl", "fake"), default="tabicl")
    return cli


def main() -> None:
    """Print precision at k against the random-ranking baseline for each dataset."""
    args = parser().parse_args()
    for name in args.datasets:
        result = measure(name, make_teacher(args.teacher))
        print(
            f"audit dataset={result.dataset} teacher={args.teacher} rows={result.rows} "
            f"k={result.k} hits={result.hits} precision_at_k={result.precision:.3f} "
            f"random={FLIP_RATE:.3f} p_value={result.p_value:.3g} "
            f"wall_seconds={result.wall_seconds:.3f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
