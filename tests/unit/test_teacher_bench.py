import importlib
import json
from pathlib import Path

import pytest

from rowsetta.core.features import teacher_frame
from scripts.bench_teacher import BENCH_JSON, ROOT, penguins_protocol, write_drift


def test_drift_protocol_is_seeded_complete_and_balanced() -> None:
    table, store = penguins_protocol()
    _, repeated = penguins_protocol()
    assert store.human == repeated.human
    assert len(store.human) == 6
    assert all(list(store.human.values()).count(label) == 2 for label in store.classes)
    assert not teacher_frame(table, store).frame.loc[list(store.human)].isna().any().any()


def test_drift_write_preserves_unrelated_measurements(tmp_path: Path) -> None:
    path = tmp_path / "bench.json"
    path.write_text('{"other": {"seconds": 12}, "teacher": {"other": 3}}')
    write_drift(0.9, path)
    assert json.loads(path.read_text()) == {
        "other": {"seconds": 12},
        "teacher": {"other": 3, "penguins_6_labels": {"accuracy": 0.9}},
    }


@pytest.mark.parametrize("document", [{}, {"teacher": {}}, {"teacher": {"penguins_6_labels": {}}}])
def test_bench_schema_requires_drift_accuracy(document: dict[str, object]) -> None:
    schema = json.loads((ROOT / "docs" / "bench.schema.json").read_text())
    validator = importlib.import_module("jsonschema")
    validator.validate(json.loads(BENCH_JSON.read_text()), schema)
    with pytest.raises(validator.ValidationError):
        validator.validate(document, schema)
