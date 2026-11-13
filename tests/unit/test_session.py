import hashlib
import importlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
import pytest
from pydantic import ValidationError

from rowsetta.core.errors import NotServed
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import load_csv


class SchemaValidator(Protocol):
    def validate(self, instance: object) -> None: ...


class ChiSquareResult(Protocol):
    pvalue: float


if TYPE_CHECKING:
    from collections.abc import Callable


SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "session.schema.json"


@pytest.fixture
def store() -> LabelStore:
    return LabelStore(
        classes=("yes", "no"),
        target="outcome",
        source=SourceRef(file_name="data.csv", sha256="a" * 64, rows=100),
    )


def answer(store: LabelStore, label: str = "yes") -> int:
    row = store.next_eval_row()
    assert row is not None
    store.set_eval(row, label)
    return row


def test_training_and_evaluation_are_disjoint(store: LabelStore) -> None:
    store.set_human(0, "yes")
    row = answer(store)
    assert row != 0
    assert store.training_rows() == {0: "yes"}
    assert not store.human.keys() & store.eval.keys()
    with pytest.raises(NotServed):
        store.set_human(row, "no")
    labels = store.training_rows()
    labels.clear()
    assert store.human == {0: "yes"}


def test_only_currently_served_row_can_be_answered(store: LabelStore) -> None:
    with pytest.raises(NotServed):
        store.set_eval(0, "yes")
    row = answer(store)
    with pytest.raises(NotServed):
        store.set_eval(row, "no")
    current = store.next_eval_row()
    assert current is not None
    assert store.next_eval_row() == current
    with pytest.raises(NotServed):
        store.set_eval(row, None)


def test_serving_is_seeded_without_replacement_and_exhausts(store: LabelStore) -> None:
    expected = np.random.default_rng(store.eval_seed).permutation(100).tolist()
    assert [answer(store) for _ in range(100)] == expected
    assert store.eval_served == expected
    assert store.next_eval_row() is None


def test_eligibility_is_checked_when_served(store: LabelStore) -> None:
    order = np.random.default_rng(store.eval_seed).permutation(100).tolist()
    store.set_human(order[0], "no")
    assert answer(store) == order[1]
    store.set_human(order[2], "yes")
    assert answer(store) == order[3]
    store.set_human(order[0], None)
    assert answer(store) == order[0]


def test_undo_human_add_edit_and_clear(store: LabelStore) -> None:
    assert store.undo() is None
    store.set_human(0, "yes")
    store.set_human(0, "no")
    store.set_human(0, None)
    assert store.undo() == 0
    assert store.human == {0: "no"}
    assert store.undo() == 0
    assert store.human == {0: "yes"}
    assert store.undo() == 0
    assert store.human == {}
    assert store.undo() is None


def test_undo_then_relabel_evaluation_keeps_the_blind_sample(store: LabelStore) -> None:
    row = answer(store)
    store.set_human(0 if row != 0 else 1, "no")
    store.undo()
    assert store.undo() == row
    assert row not in store.eval
    assert store.next_eval_row() == row
    store.set_eval(row, "no")
    assert store.eval == {row: "no"}
    assert store.eval_served == [row]
    assert store.training_rows() == {}
    assert store.undo() == row
    store.set_eval(row, None)
    with pytest.raises(NotServed):
        store.set_human(row, "yes")


def test_noop_human_edit_does_not_create_undo(store: LabelStore) -> None:
    store.set_human(0, None)
    assert store.undo() is None
    store.set_human(0, "yes")
    store.set_human(0, "yes")
    assert store.undo() == 0
    assert not store.human


def test_json_schema_and_round_trip_preserve_continuation(store: LabelStore) -> None:
    store.set_human(0, "yes")
    answer(store)
    store.next_eval_row()
    store.excluded_columns = frozenset({"id", "notes"})
    schema = json.loads(SCHEMA.read_text())
    jsonschema = importlib.import_module("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator: SchemaValidator = jsonschema.Draft202012Validator(schema)
    validator.validate(json.loads(store.to_json()))
    restored = LabelStore.from_json(store.to_json())
    assert restored == store
    assert restored.undo() == store.undo()
    assert restored.next_eval_row() == store.next_eval_row()
    row = store.next_eval_row()
    assert row is not None
    store.set_eval(row, "no")
    restored.set_eval(row, "no")
    assert restored.next_eval_row() == store.next_eval_row()


def test_source_fingerprint_retains_sample_ids() -> None:
    data = b"x,y\n1,a\n2,b\n3,c\n4,d\n"
    table = load_csv(data, max_rows=2)
    source = SourceRef.from_table("data.csv", data, table)
    assert source.sha256 == hashlib.sha256(data).hexdigest()
    assert source.rows == 4
    assert source.sampled_rows == tuple(table.frame.index)
    assert source.sample_seed == 7
    assert SourceRef.from_table("data.csv", data, load_csv(data)).sampled_rows is None
    assert SourceRef.from_table("data.csv", data + b"5,e\n", table).sha256 != source.sha256
    sampled = LabelStore(classes=("a", "b"), target="y", source=source)
    assert {answer(sampled, "a") for _ in range(2)} == set(table.frame.index)
    assert sampled.next_eval_row() is None
    assert LabelStore.from_json(sampled.to_json()) == sampled


@pytest.mark.parametrize("row", [-1, 100])
def test_reject_unknown_rows(store: LabelStore, row: int) -> None:
    with pytest.raises(ValueError, match="outside the working sample"):
        store.set_human(row, "yes")


def test_reject_unknown_class_without_changing_state(store: LabelStore) -> None:
    before = store.to_json()
    with pytest.raises(ValueError, match="session classes"):
        store.set_human(0, "maybe")
    assert store.to_json() == before
    store.next_eval_row()
    before = store.to_json()
    row = store.current_eval_row
    assert row is not None
    with pytest.raises(ValueError, match="session classes"):
        store.set_eval(row, "maybe")
    assert store.to_json() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"classes": ["yes"]},
        {"classes": ["yes", "yes"]},
        {"classes": ["", "no"]},
        {"threshold": 1.1},
        {"threshold": float("nan")},
        {"human": {"100": "yes"}},
        {"human": {"0": "maybe"}},
        {"eval": {"0": "yes"}},
        {"eval_served": [0, 0]},
        {"eval_served": [0], "human": {"0": "yes"}},
        {"current_eval_row": 0},
        {"unexpected": True},
    ],
)
def test_reject_invalid_session_files(store: LabelStore, changes: dict[str, object]) -> None:
    payload = json.loads(store.to_json())
    payload.update(changes)
    with pytest.raises(ValidationError):
        LabelStore.from_json(json.dumps(payload))


@pytest.mark.parametrize("sample", [(0, 0), (-1,), (100,)])
def test_reject_invalid_sample_ids(sample: tuple[int, ...]) -> None:
    with pytest.raises(ValidationError):
        SourceRef(file_name="data.csv", sha256="a" * 64, rows=100, sampled_rows=sample)


def test_eval_uniformity_over_ten_thousand_seeded_permutations() -> None:
    counts = np.zeros(100, dtype=np.int64)
    for seed in range(10_000):
        store = LabelStore(
            classes=("yes", "no"),
            target="outcome",
            eval_seed=seed,
            source=SourceRef(file_name="data.csv", sha256="a" * 64, rows=100),
        )
        counts[answer(store)] += 1
    # The first served row from each independent permutation is a multinomial sample.
    chisquare: Callable[[object, object], ChiSquareResult] = importlib.import_module(
        "scipy.stats"
    ).chisquare
    result = chisquare(counts, np.full(100, 100))
    assert float(result.pvalue) > 0.01


def test_undo_preserves_an_already_served_unanswered_row(store: LabelStore) -> None:
    first = answer(store)
    pending = store.next_eval_row()
    assert pending is not None
    assert store.undo() == first
    assert store.next_eval_row() == first
    store.set_eval(first, "no")
    assert store.next_eval_row() == pending
    store.set_eval(pending, None)
    assert store.next_eval_row() == pending


def test_undo_human_clear_after_that_row_was_served(store: LabelStore) -> None:
    row = store.next_eval_row()
    assert row is not None
    fresh = LabelStore(classes=store.classes, target=store.target, source=store.source)
    fresh.set_human(row, "yes")
    fresh.set_human(row, None)
    assert fresh.next_eval_row() == row
    restored = LabelStore.from_json(fresh.to_json())
    assert restored.undo() == row
    assert restored.human == {row: "yes"}
    assert row not in restored.eval_served
    assert restored.next_eval_row() != row
    assert restored.undo() == row
    assert restored.human == {}


def test_empty_source_has_no_evaluation_rows() -> None:
    store = LabelStore(
        classes=("yes", "no"),
        target="outcome",
        source=SourceRef(file_name="data.csv", sha256="a" * 64, rows=0),
    )
    assert store.next_eval_row() is None
    assert LabelStore.from_json(store.to_json()) == store
