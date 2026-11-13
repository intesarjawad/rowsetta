import importlib
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from rowsetta.core.evaluation import Measured, NeedsRows, evaluate
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.teacher import Proposals

if TYPE_CHECKING:
    from collections.abc import Callable


def sample(truth: list[str], predicted: list[str]) -> tuple[LabelStore, Proposals]:
    rows = list(range(10, 10 + len(truth)))
    store = LabelStore(
        classes=("no", "yes"),
        target="outcome",
        source=SourceRef(file_name="data.csv", sha256="a" * 64, rows=200),
        human={0: "yes"},
        eval=dict(zip(rows, truth, strict=True)),
        eval_served=rows,
    )
    proposals = Proposals(
        dict(zip(rows, predicted, strict=True)), {}, pd.DataFrame(), frozenset(), 3
    )
    return store, proposals


@pytest.mark.parametrize(
    ("correct", "n", "lo", "hi"),
    [
        (18, 20, 0.699, 0.972),
        (40, 50, 0.670, 0.888),
        (90, 100, 0.826, 0.945),
        (0, 20, 0.0, 0.161),
        (20, 20, 0.839, 1.0),
    ],
)
def test_wilson_reference_table(correct: int, n: int, lo: float, hi: float) -> None:
    store, proposals = sample(["no"] * n, ["no"] * correct + ["yes"] * (n - correct))
    result = evaluate(store, proposals)
    assert result is not None
    assert result.n == n
    assert result.accuracy.value == correct / n
    assert round(result.accuracy.lo, 3) == lo
    assert round(result.accuracy.hi, 3) == hi


@pytest.mark.parametrize("n", [0, 19])
def test_requires_twenty_eval_labels(n: int) -> None:
    assert evaluate(*sample(["no"] * n, ["no"] * n)) is None


@pytest.mark.parametrize("yes_count", [0, 2, 4])
def test_needs_rows_includes_absent_classes(yes_count: int) -> None:
    truth = ["no"] * (20 - yes_count) + ["yes"] * yes_count
    result = evaluate(*sample(truth, truth))
    assert result is not None
    assert result.balanced_accuracy == NeedsRows({"no": 20 - yes_count, "yes": yes_count})
    assert result.balanced_accuracy.kind == "needs_rows"
    assert result.per_class_recall == {"no": 1.0, "yes": None}
    assert result.majority_class == "no"
    assert result.majority_baseline == (20 - yes_count) / 20


def test_balanced_accuracy_recall_and_seeded_stratified_interval() -> None:
    truth = ["no"] * 15 + ["yes"] * 5
    predicted = ["no"] * 12 + ["yes"] * 3 + ["yes"] * 3 + ["no"] * 2
    store, proposals = sample(truth, predicted)
    result = evaluate(store, proposals)
    assert result is not None
    measured = result.balanced_accuracy
    assert isinstance(measured, Measured)
    assert measured.kind == "measured"
    reference: Callable[[list[str], list[str]], float] = importlib.import_module(
        "sklearn.metrics"
    ).balanced_accuracy_score
    assert measured.value == pytest.approx(reference(truth, predicted))
    assert result.per_class_recall == {"no": 0.8, "yes": 0.6}
    assert result.accuracy.value == 0.75
    assert result == evaluate(store, proposals)
    rng = np.random.default_rng(7)
    rates = np.zeros(2000)
    for label in store.classes:
        correct = np.array([a == b for a, b in zip(truth, predicted, strict=True) if a == label])
        rates += rng.choice(correct, size=(2000, len(correct))).mean(axis=1) / 2
    lo, hi = np.quantile(rates, [0.025, 0.975])
    assert measured.lo == pytest.approx(lo)
    assert measured.hi == pytest.approx(hi)


def test_uses_eval_labels_only_and_preserves_inputs() -> None:
    store, proposals = sample(["no"] * 10 + ["yes"] * 10, ["yes"] * 20)
    proposals = replace(proposals, label={**proposals.label, 0: "yes", 199: "no"})
    before = store.to_json()
    result = evaluate(store, proposals)
    assert result is not None
    assert result.n == 20
    assert result.accuracy.value == 0.5
    assert result.majority_class == "no"
    assert store.to_json() == before
