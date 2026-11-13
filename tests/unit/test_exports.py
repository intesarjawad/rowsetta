import importlib
import importlib.machinery
import importlib.util
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd
import pytest
from pydantic import TypeAdapter

from rowsetta.core.distill import Feature, FeatureSpec, TreeClassifier, fit_student, leaf_summary
from rowsetta.core.export.dbt import to_dbt
from rowsetta.core.export.json import Export, to_json
from rowsetta.core.export.python import to_python
from rowsetta.core.export.sql import Executed, UnsupportedDatetimeSplitError, to_sql
from tests.integration.test_sql_export import DEMO_TARGETS, demo_student
from tests.sql_support import certificate, engine, predictions
from tests.unit.test_distill import FourLeafTree, labelled, ten_rows


class SchemaValidator(Protocol):
    def validate(self, instance: object) -> None: ...


def compiled_predict(source: str, path: Path) -> Callable[[dict[str, object]], str | None]:
    path.write_text(source)
    loader = importlib.machinery.SourceFileLoader("rule", str(path))
    module = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("rule", loader))
    loader.exec_module(module)
    return module.predict


@pytest.mark.parametrize(("dataset", "target"), DEMO_TARGETS)
def test_python_identity_on_every_demo_row(dataset: str, target: str, tmp_path: Path) -> None:
    student = demo_student(dataset, target)
    predict = compiled_predict(to_python(student), tmp_path / "rule.py")
    records = student.frame.astype(object).where(student.frame.notna(), None).to_dict("records")
    assert [
        predict({str(key): value for key, value in row.items()}) for row in records
    ] == student.predict(student.frame)


@pytest.mark.parametrize("odd", [False, True])
@pytest.mark.parametrize("missing_left", [False, True])
def test_python_float32_ties_missing_categories_and_abstention(
    tmp_path: Path, *, odd: bool, missing_left: bool
) -> None:
    tree = FourLeafTree()
    lower = np.float32(0.5)
    if odd:
        lower = np.nextafter(lower, np.float32(np.inf))
    midpoint = (float(lower) + float(np.nextafter(lower, np.float32(np.inf)))) / 2
    tree.threshold[0] = float(lower)
    tree.missing_go_to_left[0] = missing_left
    frame = pd.DataFrame(
        {
            'x"': [
                np.nextafter(midpoint, -np.inf),
                midpoint,
                np.nextafter(midpoint, np.inf),
                None,
                np.nan,
                -1e30,
                1e30,
            ]
            * 4,
            "cat": [None] * 7 + ["O'Reilly"] * 7 + ["unseen"] * 7 + [np.nan] * 7,
        }
    )
    student = replace(
        fit_student(*ten_rows()),
        tree=tree,
        feature_spec=FeatureSpec(
            (Feature('x"', "numeric"), Feature("cat", "categorical", "O'Reilly"))
        ),
        leaf_purity={2: 1, 3: 0.6, 5: 1, 6: 1},
        threshold=0.8,
    )
    predict = compiled_predict(to_python(student), tmp_path / "rule.py")
    actual = [
        predict({str(key): value for key, value in row.items()}) for row in frame.to_dict("records")
    ]
    assert actual == student.predict(frame)
    assert None in actual


def test_json_schema_preserves_tree_preprocessing_and_certificate() -> None:
    student = replace(fit_student(*ten_rows()), threshold=0.8)
    facts = certificate()
    payload = json.loads(to_json(student, certificate=facts))
    schema_path = Path(__file__).resolve().parents[2] / "docs/export.schema.json"
    schema = json.loads(schema_path.read_text())
    jsonschema = importlib.import_module("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator: SchemaValidator = jsonschema.Draft202012Validator(schema)
    validator.validate(payload)
    assert payload["preprocessing"] == {
        "features": [{"column": "x", "kind": "numeric", "value": ""}]
    }
    assert payload["tree"]["input_dtype"] == "float32"
    assert payload["tree"]["nodes"][0]["threshold"] == student.tree.tree_.threshold[0]
    leaves = [node for node in payload["tree"]["nodes"] if node["kind"] == "leaf"]
    assert [leaf["prediction"] for leaf in leaves] == ["a", None]
    assert [leaf["purity"] for leaf in leaves] == [1.0, 0.6]
    assert payload["certificate"]["export_date"] == "2026-11-05"
    assert payload["certificate"]["in_sample"]["coverage"] == {"answered": 8, "total": 10}
    assert payload["schema_sha256"] == facts.schema_sha256
    assert payload["abstention_threshold"] == 0.8
    assert to_json(student, certificate=facts) == to_json(student, certificate=facts)
    assert TypeAdapter(Export).json_schema() == {
        key: value for key, value in schema.items() if key != "$schema"
    }


@pytest.mark.parametrize(("dataset", "target"), DEMO_TARGETS)
def test_json_round_trip_replays_every_demo_prediction(dataset: str, target: str) -> None:
    student = demo_student(dataset, target)
    facts = replace(
        certificate(),
        target=target,
        execution=Executed("2.0.0", len(student.frame), len(student.frame)),
    )
    document = TypeAdapter(Export).validate_json(to_json(student, certificate=facts))
    encoded = document.preprocessing.transform(student.frame).astype(np.float32)
    result: list[str | None] = []
    for row in encoded:
        node = document.tree.nodes[0]
        while node.kind == "split":
            value = row[node.feature_index]
            goes_left = node.missing_go_to_left if np.isnan(value) else value <= node.threshold
            node = document.tree.nodes[node.left if goes_left else node.right]
        result.append(node.prediction)
    assert result == student.predict(student.frame)


def test_unsplit_python_rule_preserves_quoted_labels(tmp_path: Path) -> None:
    student = fit_student(
        *labelled(pd.DataFrame({"x": [0] * 10, "answer": ["O'Reilly\nbook"] * 9 + ["other"]}))
    )
    predict = compiled_predict(to_python(student), tmp_path / "rule.py")
    assert predict({"x": None}) == "O'Reilly\nbook"


def test_python_matches_the_used_datetime_split_restriction() -> None:
    student = replace(
        fit_student(*ten_rows()), feature_spec=FeatureSpec((Feature("event time", "datetime"),))
    )
    with pytest.raises(UnsupportedDatetimeSplitError, match="event time"):
        to_python(student)


def test_four_row_missing_only_split_across_exports(tmp_path: Path) -> None:
    frame = pd.DataFrame({"x": [0.0, 1.0, None, None], "answer": ["a", "a", "b", "b"]})
    tree: TreeClassifier = importlib.import_module("sklearn.tree").DecisionTreeClassifier(
        random_state=7
    )
    tree.fit(frame[["x"]].to_numpy(), frame["answer"])
    assert np.isinf(tree.tree_.threshold[0])
    student = replace(
        fit_student(*labelled(frame)),
        tree=tree,
        feature_spec=FeatureSpec((Feature("x", "numeric"),)),
        leaf_purity={1: 1.0, 2: 1.0},
        threshold=0,
    )
    expected = student.predict(frame)
    facts = certificate()
    for dialect in ("duckdb", "sqlite", "postgres"):
        sql = to_sql(student, dialect=dialect, certificate=facts)
        assert "inf" not in sql
        # PostgreSQL's CASE and CAST syntax is also executable in DuckDB.
        execution_dialect = "duckdb" if dialect == "postgres" else dialect
        assert predictions(engine(execution_dialect).execute(sql, frame)) == expected
        files = to_dbt(student, source="t", certificate=facts, dialect=dialect)
        dbt_sql = files["models/answer_rule.sql"].replace("{{ ref('t') }}", '"t"')
        assert predictions(engine(execution_dialect).execute(dbt_sql, frame)) == expected
    predict = compiled_predict(to_python(student), tmp_path / "missing_rule.py")
    assert [predict({"x": x}) for x in [0.0, 1.0, None, float("nan")]] == expected
    payload = to_json(student, certificate=facts)
    document = TypeAdapter(Export).validate_json(payload)
    assert "null" not in json.dumps(json.loads(payload)["tree"]["nodes"][0])
    results: list[str | None] = []
    for row in document.preprocessing.transform(frame).astype(np.float32):
        node = document.tree.nodes[0]
        while node.kind == "split":
            value = row[node.feature_index]
            goes_left = node.missing_go_to_left if np.isnan(value) else value <= node.threshold
            node = document.tree.nodes[node.left if goes_left else node.right]
        results.append(node.prediction)
    assert results == expected
    conditions = [line.conditions[0][1:] for line in leaf_summary(student, frame)]
    assert conditions == [("IS NOT NULL", ""), ("IS NULL", "")]
