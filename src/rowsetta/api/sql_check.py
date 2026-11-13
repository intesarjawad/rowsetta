"""Execute an exported DuckDB rule against the complete source CSV."""

import logging
import sys
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import HTTPException

from rowsetta.api.errors import ApiError, error_body
from rowsetta.core.distill import Student
from rowsetta.core.export.sql import Executed
from rowsetta.core.table import load_csv


def sql_check(source: Path, student: Student, *, target: str, sql: str) -> Executed:
    """Return full-source identity, or reject the export with the first differing row.

    The caller supplies header-less DuckDB SQL and renders the returned execution
    facts into the final certificate only after this check succeeds.
    """
    return sql_check_data(source.read_bytes(), student, target=target, sql=sql)


def sql_check_data(data: bytes, student: Student, *, target: str, sql: str) -> Executed:
    """Verify original uploaded bytes without writing user data to a temporary file."""
    table = load_csv(data, max_rows=sys.maxsize)
    expected = student.predict(table.frame)
    with duckdb.connect(":memory:") as connection:
        connection.register("t", table.frame)
        result = connection.execute(sql).fetchdf()
    actual = [None if pd.isna(value) else str(value) for value in result[f"predicted_{target}"]]
    if len(actual) != len(expected):
        row = min(len(actual), len(expected))
        _reject(row, f"SQL returned {len(actual)} rows; expected {len(expected)}")
    for row, (prediction, label) in enumerate(zip(actual, expected, strict=True)):
        if prediction != label:
            _reject(row, "SQL prediction differs from the student")
    return Executed(duckdb.__version__, len(expected), len(expected))


def _reject(row: int, reason: str) -> None:
    message = f"SQL export mismatch at source row {row}: {reason}."
    logging.getLogger(__name__).error(message)
    error = ApiError(
        message,
        "rowsetta open data.csv; re-teach the rule and retry the export.",
        status_code=500,
    )
    raise HTTPException(
        status_code=500,
        detail={**error_body(error), "row_id": row},
    ) from error
