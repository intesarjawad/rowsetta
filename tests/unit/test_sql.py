import hashlib
import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from rowsetta.core.distill import (
    Feature,
    FeatureSpec,
    NoDifference,
    OtherBetter,
    RuleBetter,
    fit_student,
    leaf_summary,
)
from rowsetta.core.export import sql
from rowsetta.core.export.sql import Dialect, Executed, SqlOptions, to_sql, tree_to_sql
from tests.sql_support import certificate, engine, predictions
from tests.unit.test_distill import FourLeafTree, labelled, ten_rows

pytestmark = pytest.mark.native


@pytest.mark.parametrize(
    "dialect", ["duckdb", "sqlite", pytest.param("postgres", marks=pytest.mark.pg)]
)
def test_student_export_preserves_abstention_and_confidence(dialect: Dialect) -> None:
    table, store, proposals = ten_rows()
    student = replace(fit_student(table, store, proposals), threshold=0.8)
    facts = certificate()
    sql = to_sql(student, dialect=dialect, certificate=facts)
    result = engine(dialect).execute(sql, table.frame)
    assert predictions(result) == student.predict(table.frame) == ["a"] * 5 + [None] * 5
    assert result["predicted_answer_confidence"].tolist() == [1.0] * 5 + [0.6] * 5
    assert result["predicted_answer_confidence"].dtype == np.dtype("float64")
    assert sql.startswith(facts.header() + "SELECT *, ")


@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
def test_four_leaves_reuse_summary_literals_and_escape_names(dialect: Dialect) -> None:
    tree = FourLeafTree()
    spec = FeatureSpec((Feature('x"', "numeric"), Feature("cat", "categorical", "O'Reilly")))
    frame = pd.DataFrame(
        {'x"': [0, 0, 1, 1, np.nan], "cat": [None, "O'Reilly", "b", "O'Reilly", "b"]}
    )
    student = replace(
        fit_student(*ten_rows()),
        tree=tree,
        feature_spec=spec,
        leaf_purity={2: 1, 3: 0.6, 5: 1, 6: 1},
        threshold=0.8,
        teacher_labels={},
    )
    labels = ["a", None, "b", "a"]
    sql = tree_to_sql(
        tree,
        feature_spec=spec,
        target='an"swer',
        dialect=dialect,
        options=SqlOptions(table_name='t";', leaf_labels=labels),
    )
    result = engine(dialect).execute(sql, frame, 't";')
    assert predictions(result, 'an"swer') == student.predict(frame)
    for line in leaf_summary(student, frame):
        for _, _, literal in line.conditions:
            assert literal in sql
    assert '"x"""' in sql
    assert "'O''Reilly'" in sql
    assert not sql.startswith("--")


@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
def test_default_majority_labels_and_literal_escaping(dialect: Dialect) -> None:
    table, store, proposals = labelled(
        pd.DataFrame({"x": [0] * 5 + [1] * 5, "answer": ["O'Reilly"] * 5 + ["other"] * 5})
    )
    student = fit_student(table, store, proposals)
    sql = tree_to_sql(
        student.tree, feature_spec=student.feature_spec, target="answer", dialect=dialect
    )
    assert "'O''Reilly'" in sql
    assert predictions(engine(dialect).execute(sql, table.frame)) == student.predict(table.frame)


@pytest.mark.parametrize(
    "dialect", ["duckdb", "sqlite", pytest.param("postgres", marks=pytest.mark.pg)]
)
def test_unsplit_tree_and_four_decimal_purity(dialect: Dialect) -> None:
    table, store, proposals = labelled(
        pd.DataFrame({"x": [0] * 15, "answer": ["a"] * 10 + ["b"] * 5})
    )
    student = fit_student(table, store, proposals)
    sql = tree_to_sql(
        student.tree, feature_spec=student.feature_spec, target="answer", dialect=dialect
    )
    result = engine(dialect).execute(sql, table.frame)
    assert "CASE" not in sql
    assert predictions(result) == ["a"] * 15
    assert result["predicted_answer_confidence"].tolist() == [0.6667] * 15
    assert result["predicted_answer_confidence"].dtype == np.dtype("float64")


@pytest.mark.pg
def test_postgres_results_are_aligned_to_source_rows() -> None:
    frame = pd.DataFrame({"x": [2, 1, 3], "__test_row_ordinal": [9, 8, 7]})
    result = engine("postgres").execute(
        "SELECT *, x * 10 AS prediction FROM t ORDER BY x DESC", frame
    )
    assert result["x"].tolist() == [2, 1, 3]
    assert result["prediction"].tolist() == [20, 10, 30]
    assert result["__test_row_ordinal"].tolist() == [9, 8, 7]


def test_leaf_labels_must_match_leaf_count() -> None:
    student = fit_student(*ten_rows())
    with pytest.raises(ValueError, match="one label per leaf"):
        tree_to_sql(
            student.tree,
            feature_spec=student.feature_spec,
            target="answer",
            dialect="duckdb",
            options=SqlOptions(leaf_labels=[None]),
        )


def test_certificate_target_must_match_sql() -> None:
    student = fit_student(*ten_rows())
    with pytest.raises(ValueError, match="certificate target"):
        tree_to_sql(
            student.tree,
            feature_spec=student.feature_spec,
            target="wrong",
            dialect="duckdb",
            options=SqlOptions(certificate=certificate()),
        )


def test_certificate_contains_all_facts_and_ordered_schema_hash() -> None:
    facts = certificate()
    header = facts.header()
    expected_hash = hashlib.sha256(
        json.dumps([["x", "float64"]], separators=(",", ":")).encode()
    ).hexdigest()
    assert facts.schema_sha256 == expected_hash
    for text in (
        "2026-11-05",
        "Dataset rows: 10",
        expected_hash,
        "DuckDB DOUBLE; PostgreSQL DOUBLE PRECISION; SQLite REAL",
        'Classes: ["a", "b"]',
        "depth 1, 2 leaves",
        "In-sample agreement: 7/8; coverage 8/10\n",
        "Cross-fitted agreement: 7/8; coverage 8/10; 95% interval [0.5000, 0.9900]",
        "Rule conditional evaluation accuracy (answered rows)",
        "Teacher conditional evaluation accuracy (confident predictions)",
        "Direct tree, same settings",
        "Direct tree, tuned",
        "McNemar",
        "Abstention threshold: 0.8",
        "tabicl version: 2.2.0",
        "b" * 64,
        "Execution: not executed (browser demo)",
    ):
        assert text in header
    changed = replace(facts, columns=(replace(facts.columns[0], source_type="int64"),))
    assert changed.schema_sha256 != facts.schema_sha256
    assert (
        replace(facts, execution=Executed("v2.0.0", 10, 10))
        .header()
        .endswith("-- Execution: DuckDB v2.0.0: 10/10 rows identical\n")
    )


@pytest.mark.parametrize("verdict", [RuleBetter(0.0039), OtherBetter(0.0039)])
def test_certificate_reports_mcnemar_direction(verdict: RuleBetter | OtherBetter) -> None:
    assert f"{verdict.kind}, p=0.0039" in replace(certificate(), comparison=verdict).header()


def test_multiline_certificate_values_cannot_escape_comments() -> None:
    facts = replace(certificate(), target="answer\nDROP TABLE t;", tool_name="tool\rSELECT 1;")
    assert all(line.startswith("-- ") for line in facts.header().splitlines())


def test_to_sql_only_builds_public_export_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    student = replace(fit_student(*ten_rows()), threshold=0.8)
    facts = certificate()

    def spy(tree: object, **arguments: object) -> str:
        assert tree is student.tree
        assert arguments == {
            "feature_spec": student.feature_spec,
            "target": "answer",
            "dialect": "sqlite",
            "options": SqlOptions(table_name="source", leaf_labels=["a", None], certificate=facts),
        }
        return "exported"

    monkeypatch.setattr(sql, "tree_to_sql", spy)
    assert to_sql(student, dialect="sqlite", table_name="source", certificate=facts) == "exported"


def test_used_datetime_split_names_column_and_recovery() -> None:
    student = fit_student(*ten_rows())
    spec = FeatureSpec((Feature("event time", "datetime"),))
    with pytest.raises(sql.UnsupportedDatetimeSplitError) as caught:
        tree_to_sql(student.tree, feature_spec=spec, target="answer", dialect="duckdb")
    assert caught.value.column == "event time"
    assert "event time" in caught.value.what
    assert caught.value.next_step.startswith("rowsetta open ")
    assert "exclude column 'event time'" in caught.value.next_step
    assert "re-teach without it" in caught.value.next_step


def test_unused_datetime_feature_does_not_block_export() -> None:
    student = fit_student(*ten_rows())
    spec = FeatureSpec((*student.feature_spec.features, Feature("event time", "datetime")))
    exported = tree_to_sql(student.tree, feature_spec=spec, target="answer", dialect="duckdb")
    assert "event time" not in exported


def test_zero_evaluation_pairs_are_not_measured() -> None:
    assert (
        "McNemar (rule versus tuned direct tree): not measured"
        in replace(certificate(), comparison=NoDifference(0)).header()
    )


def test_certificate_names_accuracy_conditioned_on_confident_predictions() -> None:
    facts = certificate()
    header = facts.header()
    assert (
        "Teacher conditional evaluation accuracy (confident predictions): 7/8; coverage 8/10"
        in header
    )
    assert "Rule conditional evaluation accuracy (answered rows): 7/8; coverage 8/10" in header
    assert "Teacher evaluation accuracy:" not in header
