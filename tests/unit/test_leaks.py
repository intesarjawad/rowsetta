import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rowsetta.core.features import teacher_frame
from rowsetta.core.leaks import find_leaks
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import Table, load_csv

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "src" / "rowsetta" / "datasets"


def labelled_table(data: bytes, target: str = "answer") -> tuple[Table, LabelStore]:
    table = load_csv(data)
    store = LabelStore(
        target=target,
        classes=tuple(sorted(str(value) for value in table.frame[target].unique())),
        source=SourceRef.from_table("test.csv", data, table),
        human={int(row): str(value) for row, value in enumerate(table.frame[target])},
    )
    return table, store


@pytest.fixture
def synthetic() -> tuple[Table, LabelStore]:
    frame = pd.DataFrame({"noise": [0, 1, 0] * 20, "answer": ["a", "b"] * 30})
    return labelled_table(frame.to_csv(index=False).encode())


@pytest.mark.parametrize("labels", [29, 30])
def test_requires_thirty_human_labels_and_two_classes(
    labels: int, synthetic: tuple[Table, LabelStore]
) -> None:
    table, store = synthetic
    table.frame["noise"] = np.arange(60)
    store.human = dict(list(store.human.items())[:labels])
    if labels == 30:
        store.human = dict.fromkeys(store.human, "a")
    while (row := store.next_eval_row()) is not None:
        store.set_eval(row, "b")
    assert find_leaks(table, store) == []


def test_identifier_and_name_hints() -> None:
    frame = pd.DataFrame(
        {
            "row_id": np.arange(60),
            "customer_id": ["a", "b", "c"] * 20,
            "uuidish": [0, 1, 0] * 20,
            "notes": [f"free text {row}" for row in range(60)],
            "answer": ["a", "b"] * 30,
        }
    )
    table, store = labelled_table(frame.to_csv(index=False).encode())
    hints = find_leaks(table, store)
    assert {(hint.column, hint.kind) for hint in hints} == {
        ("row_id", "identifier"),
        ("row_id", "name"),
        ("customer_id", "name"),
    }
    assert all(hint.score is None for hint in hints)


@pytest.mark.parametrize("categorical", [False, True])
def test_near_copy_uses_human_rows_and_preserves_source_ids(*, categorical: bool) -> None:
    frame = pd.DataFrame({"copy": [0, 1] * 40, "answer": ["a", "b"] * 40})
    if categorical:
        frame["copy"] = frame["copy"].map({0: "left", 1: "right"})
    table, store = labelled_table(frame.to_csv(index=False).encode())
    store.human = {row: label for row, label in store.human.items() if row % 4 != 0}
    while (row := store.next_eval_row()) is not None:
        store.set_eval(row, "b")
    hints = find_leaks(table, store)
    assert [(hint.column, hint.kind, hint.score) for hint in hints] == [
        ("copy", "single-column", 1.0)
    ]
    assert "100%" in hints[0].reason


def test_exclusion_removes_warning_and_teacher_feature() -> None:
    frame = pd.DataFrame({"copy": [0, 1] * 30, "noise": [0, 1, 0] * 20, "answer": ["a", "b"] * 30})
    table, store = labelled_table(frame.to_csv(index=False).encode())
    assert any(hint.column == "copy" for hint in find_leaks(table, store))
    store.excluded_columns = frozenset({"copy"})
    assert list(teacher_frame(table, store).frame.columns) == ["noise"]
    assert find_leaks(table, store) == []
    store.excluded_columns = frozenset({"copy", "noise"})
    assert find_leaks(table, store) == []


def test_penguins_is_clean() -> None:
    table, store = labelled_table((DATASETS / "penguins.csv").read_bytes(), "species")
    assert find_leaks(table, store) == []


def test_bank_fixture_is_seeded_and_balanced() -> None:
    bank = pd.read_csv(DATASETS / "bank.csv")
    rng = np.random.default_rng(7)
    expected = {
        str(int(row)): label
        for label in sorted(bank["y"].unique())
        for row in rng.choice(bank.index[bank["y"] == label], size=30, replace=False)
    }
    fixture = json.loads((ROOT / "tests/fixtures/bank_labels.json").read_text())
    assert fixture == expected
    assert Counter(fixture.values()) == {"no": 30, "yes": 30}


@pytest.mark.parametrize("categorical", [False, True])
def test_missing_values_do_not_prevent_detection(*, categorical: bool) -> None:
    values = [0.0, 1.0] * 30
    values[0] = np.nan
    frame = pd.DataFrame({"copy": values, "answer": ["a", "b"] * 30})
    if categorical:
        frame["copy"] = frame["copy"].map({0: "left", 1: "right"})
    table, store = labelled_table(frame.to_csv(index=False).encode())
    hints = find_leaks(table, store)
    assert [(hint.column, hint.kind) for hint in hints] == [("copy", "single-column")]


def test_unique_categorical_and_non_integer_numeric_columns() -> None:
    frame = pd.DataFrame(
        {
            "key": [f"k{row}" for row in range(30)],
            "continuous": np.arange(30) + 0.5,
            "descending": np.arange(30)[::-1],
            "repeated": [0, 1, 2] * 10,
            "answer": ["a", "b"] * 15,
        }
    )
    table, store = labelled_table(frame.to_csv(index=False).encode())
    assert [(hint.column, hint.kind) for hint in find_leaks(table, store)] == [
        ("key", "identifier")
    ]


def test_name_check_still_applies_to_dropped_text() -> None:
    frame = pd.DataFrame(
        {"customer_ID": [f"customer-{row}" for row in range(60)], "answer": ["a", "b"] * 30}
    )
    table, store = labelled_table(frame.to_csv(index=False).encode())
    assert [(hint.column, hint.kind) for hint in find_leaks(table, store)] == [
        ("customer_ID", "name")
    ]
