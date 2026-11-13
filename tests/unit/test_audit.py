import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from rowsetta.core.audit import AUDIT_FOLDS, NeedAuditLabelsError, audit_labels
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import Table, load_csv
from rowsetta.teachers.fake import FakeTeacher


def clusters(answers: list[str]) -> tuple[Table, LabelStore]:
    """Two well separated clusters: rows 0 to 19 near 0, rows 20 to 39 near 100."""
    x = [index % 5 for index in range(20)] + [100 + index % 5 for index in range(20)]
    data = pd.DataFrame({"x": x, "answer": answers}).to_csv(index=False).encode()
    table = load_csv(data)
    store = LabelStore(
        classes=("a", "b"),
        target="answer",
        source=SourceRef.from_table("data.csv", data, table),
        human=dict(enumerate(answers)),
    )
    return table, store


class SpyTeacher(FakeTeacher):
    """Records which source rows each fit saw and which rows each prediction scored."""

    def __init__(self) -> None:
        super().__init__()
        self.fits: list[set[int]] = []
        self.predictions: list[set[int]] = []

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        self.fits.append({int(row) for row in x.index})
        super().fit(x, y)

    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        self.predictions.append({int(row) for row in x.index})
        return super().predict_proba(x)


def test_no_row_is_in_its_own_fit_and_every_label_is_scored_once() -> None:
    table, store = clusters(["a"] * 20 + ["b"] * 20)
    teacher = SpyTeacher()
    suspects = audit_labels(teacher, table, store)
    assert len(teacher.fits) == AUDIT_FOLDS
    for fitted, scored in zip(teacher.fits, teacher.predictions, strict=True):
        assert not fitted & scored
        assert fitted | scored == set(store.human)
    assert sorted(row for scored in teacher.predictions for row in scored) == sorted(store.human)
    assert sorted(suspect.row_id for suspect in suspects) == sorted(store.human)


def test_flipped_labels_rank_first_with_the_likely_class() -> None:
    answers = ["a"] * 20 + ["b"] * 20
    answers[3], answers[27] = "b", "a"
    table, store = clusters(answers)
    suspects = audit_labels(FakeTeacher(), table, store)
    assert {suspect.row_id for suspect in suspects[:2]} == {3, 27}
    assert {(suspect.given, suspect.likely) for suspect in suspects[:2]} == {("b", "a"), ("a", "b")}
    probabilities = [suspect.given_probability for suspect in suspects]
    assert probabilities == sorted(probabilities)
    assert all(0 <= probability <= 1 for probability in probabilities)


def test_ranking_is_reproducible() -> None:
    table, store = clusters(["a", "b"] * 20)
    assert audit_labels(FakeTeacher(), table, store) == audit_labels(FakeTeacher(), table, store)


def test_evaluation_labels_are_never_fitted_or_audited() -> None:
    table, store = clusters(["a"] * 20 + ["b"] * 20)
    for row in (0, 39):
        del store.human[row]
    store.eval_served = [0, 39]
    store.eval = {0: "a", 39: "b"}
    teacher = SpyTeacher()
    suspects = audit_labels(teacher, table, store)
    seen = {row for rows in (*teacher.fits, *teacher.predictions) for row in rows}
    assert not seen & {0, 39}
    assert {suspect.row_id for suspect in suspects} == set(store.human)


def test_too_few_labels_per_class_names_what_is_missing() -> None:
    table, store = clusters(["a"] * 20 + ["b"] * 20)
    store.human = {row: label for row, label in store.human.items() if row < 23}
    with pytest.raises(NeedAuditLabelsError) as raised:
        audit_labels(FakeTeacher(), table, store)
    assert raised.value.missing == {"b": AUDIT_FOLDS - 3}
    assert raised.value.next_step == "rowsetta demo; label 2 more rows of: b"
