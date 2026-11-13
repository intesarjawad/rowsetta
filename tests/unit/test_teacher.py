import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from rowsetta.core.features import teacher_frame
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import ColumnInfo, Table, load_csv
from rowsetta.core.teacher import predict_table, proposals_from_proba
from rowsetta.teachers.fake import FakeTeacher


@pytest.fixture
def sample() -> tuple[Table, LabelStore]:
    table = load_csv(b"x,outcome\n0,a\n1,a\n9,b\n10,b\n2,a\n8,b\n")
    table.frame.index = pd.Index([10, 20, 30, 40, 50, 60])
    store = LabelStore(
        classes=("b", "a"),
        target="outcome",
        source=SourceRef(
            file_name="data.csv",
            sha256="a" * 64,
            rows=100,
            sampled_rows=(10, 20, 30, 40, 50, 60),
        ),
        human={10: "a", 20: "a", 30: "b", 40: "b"},
    )
    return table, store


def test_feature_rules_preserve_missing_values_and_source_ids(
    sample: tuple[Table, LabelStore],
) -> None:
    table, store = sample
    frame = table.frame.assign(
        date=pd.Series(
            ["1970-01-02", None, "1970-01-03", "bad", "1969-12-31", "1970-01-01T12:00Z"],
            index=table.frame.index,
        ),
        text=list("abcdef"),
        kept=list("aaabbb"),
        excluded=1,
    )
    columns = (
        *table.columns,
        ColumnInfo("date", "datetime", 0.8, 0.1),
        ColumnInfo("text", "text", 1, 0),
        ColumnInfo("kept", "text", 0.5, 0),
        ColumnInfo("excluded", "numeric", 0.1, 0),
    )
    store.excluded_columns = frozenset({"excluded"})
    prepared = teacher_frame(Table(frame, columns, 100), store)
    assert list(prepared.frame.columns) == ["x", "date", "kept"]
    assert prepared.dropped_columns == ("text",)
    np.testing.assert_allclose(prepared.frame["date"], [1, np.nan, 2, np.nan, -1, 0.5])
    assert prepared.frame.index.equals(table.frame.index)
    assert "date" not in table.frame


def test_batching_and_eval_labels_do_not_enter_fit(sample: tuple[Table, LabelStore]) -> None:
    table, store = sample
    row = store.next_eval_row()
    assert row is not None
    store.set_eval(row, "b" if row == 50 else "a")
    progress: list[tuple[int, int]] = []
    teacher = FakeTeacher()
    proposals = predict_table(
        teacher,
        table,
        store,
        batch_rows=2,
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert proposals.label == {10: "a", 20: "a", 30: "b", 40: "b", 50: "a", 60: "b"}
    assert set(proposals.confidence) == {50, 60}
    assert proposals.proba.loc[list(store.human)].isna().all().all()
    assert proposals.proba.loc[[row]].notna().all().all()
    assert proposals.abstained == frozenset()
    assert progress[-1] == (2, 2)
    repeated = predict_table(FakeTeacher(), table, store, batch_rows=1)
    pd.testing.assert_frame_equal(proposals.proba, repeated.proba)


def test_probability_order_generation_and_ties(sample: tuple[Table, LabelStore]) -> None:
    _, store = sample
    proba = np.tile([0.5, 0.5], (6, 1))
    result = proposals_from_proba(proba, ("b", "a"), store, generation=12)
    assert result.generation == 12
    assert result.label[50] == "b"
    assert result.confidence[50] == 0.5
    np.testing.assert_array_equal(proba, np.full((6, 2), 0.5))


@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_abstention_at_threshold_boundaries(
    threshold: float, sample: tuple[Table, LabelStore]
) -> None:
    _, store = sample
    store.threshold = threshold
    proba = np.tile([0.5, 0.5], (6, 1))
    proba[5] = [0.0, 1.0]

    result = proposals_from_proba(proba, store.classes, store, generation=0)

    assert result.label[50] == ("unsure" if threshold == 1 else "b")
    assert result.label[60] == "a"
    assert result.abstained == (frozenset({50}) if threshold == 1 else frozenset())
    assert result.confidence == {50: 0.5, 60: 1.0}
    assert {row: result.label[row] for row in store.human} == store.human
    np.testing.assert_array_equal(result.proba.loc[[50, 60]], proba[[4, 5]])


@pytest.mark.parametrize(
    "proba",
    [np.ones((6, 1)), np.full((6, 2), np.nan), np.full((6, 2), 0.8), np.tile([-0.1, 1.1], (6, 1))],
)
def test_invalid_model_output_is_rejected(
    proba: NDArray[np.float64], sample: tuple[Table, LabelStore]
) -> None:
    with pytest.raises(ValueError, match="probabilit"):
        proposals_from_proba(proba, ("b", "a"), sample[1], generation=0)


def test_insufficient_labels_and_invalid_batch_size(sample: tuple[Table, LabelStore]) -> None:
    table, store = sample
    with pytest.raises(ValueError, match="batch_rows"):
        predict_table(FakeTeacher(), table, store, batch_rows=0)
    store.set_human(10, None)
    with pytest.raises(ValueError, match="at least 2"):
        predict_table(FakeTeacher(), table, store)


def test_fake_handles_categoricals_missing_and_unseen_values() -> None:
    train = pd.DataFrame({"n": [0, 1, 9, 10], "cat": ["a", None, "b", "b"]})
    teacher = FakeTeacher()
    teacher.fit(train, pd.Series(["a", "a", "b", "b"]))
    query = pd.DataFrame({"n": [np.nan, 1, 9], "cat": ["unseen", "a", "b"]})
    probabilities = teacher.predict_proba(query)
    assert np.isfinite(probabilities).all()
    np.testing.assert_allclose(probabilities.sum(axis=1), 1)
    assert probabilities[1].argmax() == 0
    assert probabilities[2].argmax() == 1


def test_fake_delay_is_applied_only_during_prediction(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setenv("ROWSETTA_FAKE_DELAY_MS", "125")
    monkeypatch.setattr("rowsetta.teachers.fake.sleep", waits.append)
    teacher = FakeTeacher()
    frame = pd.DataFrame({"x": [0, 1, 9, 10]})
    teacher.fit(frame, pd.Series(["a", "a", "b", "b"]))
    assert waits == []
    teacher.predict_proba(frame)
    assert waits == [0.125]


def test_fit_receives_only_human_rows_and_progress_counts_batches(
    sample: tuple[Table, LabelStore],
) -> None:
    class RecordingTeacher(FakeTeacher):
        def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
            assert tuple(x.index) == (10, 20, 30, 40)
            assert tuple(y.index) == tuple(x.index)
            assert y.to_dict() == {10: "a", 20: "a", 30: "b", 40: "b"}
            super().fit(x, y)

    table, store = sample
    row = store.next_eval_row()
    assert row is not None
    store.set_eval(row, "b")
    progress: list[tuple[int, int]] = []
    predict_table(
        RecordingTeacher(),
        table,
        store,
        batch_rows=1,
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert progress == [(0, 2), (1, 2), (2, 2)]


def test_no_features_is_actionable(sample: tuple[Table, LabelStore]) -> None:
    table, store = sample
    store.excluded_columns = frozenset({"x"})
    with pytest.raises(ValueError, match="Include a numeric or categorical column"):
        teacher_frame(table, store)


@pytest.mark.native
def test_core_import_boundary() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, rowsetta.core.workspace; "
                "assert not {'torch','fastapi','duckdb','tabicl'} & set(sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
