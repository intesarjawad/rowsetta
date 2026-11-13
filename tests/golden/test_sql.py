import os
from pathlib import Path

import pytest

from rowsetta.core.distill import leaf_summary
from rowsetta.core.export.sql import Dialect, SqlOptions, tree_to_sql
from tests.integration.test_sql_export import DEMO_TARGETS, demo_student
from tests.sql_support import engine, predictions

pytestmark = pytest.mark.native
GOLDENS = Path(__file__).parent / "sql"


@pytest.mark.parametrize(("dataset", "target"), DEMO_TARGETS)
@pytest.mark.parametrize("dialect", ["duckdb", "sqlite", "postgres"])
def test_sql_golden(dataset: str, target: str, dialect: Dialect) -> None:
    student = demo_student(dataset, target)
    exported = tree_to_sql(
        student.tree,
        feature_spec=student.feature_spec,
        target=target,
        dialect=dialect,
        options=SqlOptions(
            leaf_labels=[line.label for line in leaf_summary(student, student.frame.iloc[:0])]
        ),
    )
    path = GOLDENS / f"{dataset}.{dialect}.sql"
    if os.environ.get("ROWSETTA_UPDATE_SQL_GOLDENS") == "1":
        GOLDENS.mkdir(exist_ok=True)
        path.write_text(exported)
    assert path.read_text() == exported, "Regenerate SQL fixtures with make golden."
    # PostgreSQL execution is covered by pg-marked identity tests.
    if dialect != "postgres":
        assert predictions(engine(dialect).execute(path.read_text(), student.frame), target) == (
            student.predict(student.frame)
        )
