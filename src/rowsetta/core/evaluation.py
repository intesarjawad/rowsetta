from collections import Counter
from dataclasses import dataclass, field
from math import sqrt
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from rowsetta.core.session import LabelStore
from rowsetta.core.teacher import Proposals

MIN_EVAL_ROWS = 20
MIN_EVAL_PER_CLASS = 5
WILSON_Z = 1.959964
BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 7
LOWER_QUANTILE = 0.025
UPPER_QUANTILE = 0.975


@dataclass(frozen=True)
class Measured:
    """A measured rate and its 95% confidence interval."""

    value: float
    lo: float
    hi: float
    kind: Literal["measured"] = field(default="measured", init=False)


@dataclass(frozen=True)
class NeedsRows:
    """Evaluation support for every configured class while measurement is withheld."""

    counts: dict[str, int]
    kind: Literal["needs_rows"] = field(default="needs_rows", init=False)


@dataclass(frozen=True)
class EvalResult:
    """Teacher performance on the blind evaluation sample only."""

    n: int
    accuracy: Measured
    balanced_accuracy: Measured | NeedsRows
    per_class_recall: dict[str, float | None]
    majority_class: str
    majority_baseline: float


def evaluate(store: LabelStore, proposals: Proposals) -> EvalResult | None:
    """Measure raw teacher predictions once twenty evaluation labels are available.

    Threshold abstention does not change these metrics. Missing proposal labels
    raise KeyError; callers must supply predictions covering the evaluation set.
    Bootstrap draws use a local fixed seed, independent of active selection.
    """
    n = len(store.eval)
    if n < MIN_EVAL_ROWS:
        return None
    counts = Counter(store.eval.values())
    support = {label: counts[label] for label in store.classes}
    correct_by_class = {
        label: np.array(
            [proposals.label[row] == truth for row, truth in store.eval.items() if truth == label],
            dtype=np.bool_,
        )
        for label in store.classes
    }
    recalls = {
        label: float(correct.mean()) if len(correct) >= MIN_EVAL_PER_CLASS else None
        for label, correct in correct_by_class.items()
    }
    correct_count = sum(int(correct.sum()) for correct in correct_by_class.values())
    balanced: Measured | NeedsRows
    if any(count < MIN_EVAL_PER_CLASS for count in support.values()):
        balanced = NeedsRows(support)
    else:
        balanced = _balanced_accuracy(correct_by_class)
    majority_class = max(store.classes, key=lambda label: support[label])
    return EvalResult(
        n=n,
        accuracy=_wilson(correct_count, n),
        balanced_accuracy=balanced,
        per_class_recall=recalls,
        majority_class=majority_class,
        majority_baseline=support[majority_class] / n,
    )


def _wilson(correct: int, n: int) -> Measured:
    value = correct / n
    z_squared = WILSON_Z**2
    denominator = 1 + z_squared / n
    center = (value + z_squared / (2 * n)) / denominator
    half_width = WILSON_Z * sqrt(value * (1 - value) / n + z_squared / (4 * n**2)) / denominator
    return Measured(value, max(0.0, center - half_width), min(1.0, center + half_width))


def _balanced_accuracy(correct_by_class: dict[str, NDArray[np.bool_]]) -> Measured:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    rates = np.zeros(BOOTSTRAP_RESAMPLES)
    value = 0.0
    for correct in correct_by_class.values():
        # Retain each class's observed support rather than resampling pooled rows.
        draws = rng.choice(correct, size=(BOOTSTRAP_RESAMPLES, len(correct)))
        rates += draws.mean(axis=1) / len(correct_by_class)
        value += float(correct.mean()) / len(correct_by_class)
    lo, hi = np.quantile(rates, [LOWER_QUANTILE, UPPER_QUANTILE])
    return Measured(value, float(lo), float(hi))
