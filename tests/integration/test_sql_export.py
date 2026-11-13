from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from rowsetta.api.sql_check import sql_check
from rowsetta.core.distill import Student, fit_student, leaf_summary
from rowsetta.core.export.sql import Dialect, SqlOptions, tree_to_sql
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import load_csv
from rowsetta.core.teacher import Proposals
from tests.sql_support import engine, predictions
from tests.unit.test_distill import DATASETS, ten_rows

pytestmark = pytest.mark.native
DEMO_TARGETS = [("penguins", "species"), ("bank", "y"), ("adult", "income")]
DIALECTS = ["duckdb", "sqlite", pytest.param("postgres", marks=pytest.mark.pg)]


def demo_student(dataset: str, target: str) -> Student:
    path = DATASETS / f"{dataset}.csv"
    data = path.read_bytes()
    table = load_csv(data)
    labels = {row: str(value) for row, value in enumerate(table.frame[target])}
    store = LabelStore(
        classes=tuple(sorted(set(labels.values()))),
        target=target,
        source=SourceRef.from_table(path.name, data, table),
        human=labels,
    )
    proposals = Proposals(labels.copy(), {}, pd.DataFrame(), frozenset(), 0)
    return replace(fit_student(table, store, proposals), threshold=0.9)


@pytest.mark.parametrize(("dataset", "target"), DEMO_TARGETS)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_demo_identity_on_every_row(dataset: str, target: str, dialect: Dialect) -> None:
    path = DATASETS / f"{dataset}.csv"
    table = load_csv(path.read_bytes())
    student = demo_student(dataset, target)
    sql = tree_to_sql(
        student.tree,
        feature_spec=student.feature_spec,
        target=target,
        dialect=dialect,
        options=SqlOptions(
            leaf_labels=[line.label for line in leaf_summary(student, table.frame.iloc[:0])]
        ),
    )
    result = engine(dialect).execute(sql, table.frame)
    assert predictions(result, target) == student.predict(table.frame)
    assert len(result) == table.source_rows
    if dialect == "duckdb":
        executed = sql_check(path, student, target=target, sql=sql)
        assert executed.identical == executed.total == table.source_rows
        assert executed.engine_version


def test_checker_uses_entire_source_with_loader_rules(tmp_path: Path) -> None:
    student = fit_student(*ten_rows())
    frame = pd.DataFrame({"x": [0, 1] * 6001})
    source = tmp_path / "full.csv"
    source.write_bytes(b"\xef\xbb\xbf" + frame.to_csv(index=False, sep=";").encode())
    sql = tree_to_sql(
        student.tree, feature_spec=student.feature_spec, target="answer", dialect="duckdb"
    )
    result = sql_check(source, student, target="answer", sql=sql)
    assert result.identical == result.total == 12002


def test_checker_rejects_corrupted_threshold_with_500_and_source_row(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    table, store, proposals = ten_rows()
    student = fit_student(table, store, proposals)
    source = tmp_path / "source.csv"
    source.write_bytes(table.frame.to_csv(index=False).encode())
    sql = tree_to_sql(
        student.tree, feature_spec=student.feature_spec, target="answer", dialect="duckdb"
    )
    assert "0.5000000298023224" in sql
    corrupted = sql.replace("0.5000000298023224", "1.5")
    with pytest.raises(HTTPException) as caught:
        sql_check(source, student, target="answer", sql=corrupted)
    assert caught.value.status_code == 500
    assert "source row 5" in str(caught.value.detail)
    assert "source row 5" in caplog.text


def test_checker_rejects_wrong_row_count(tmp_path: Path) -> None:
    student = fit_student(*ten_rows())
    source = tmp_path / "source.csv"
    source.write_bytes(student.frame.to_csv(index=False).encode())
    with pytest.raises(HTTPException) as caught:
        sql_check(
            source, student, target="answer", sql="SELECT 'a' AS predicted_answer FROM t LIMIT 1"
        )
    assert caught.value.status_code == 500
    assert "SQL returned 1 rows; expected 10" in str(caught.value.detail)
