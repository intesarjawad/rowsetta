import os
import sqlite3
from datetime import date
from typing import Protocol

import duckdb
import pandas as pd
import psycopg

from rowsetta.core.distill import Count, Coverage, NoDifference, Rate
from rowsetta.core.export.sql import Certificate, ColumnType, Dialect, NotExecuted


class SqlEngine(Protocol):
    def execute(self, sql: str, frame: pd.DataFrame, table_name: str = "t") -> pd.DataFrame: ...


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class DuckEngine:
    def execute(self, sql: str, frame: pd.DataFrame, table_name: str = "t") -> pd.DataFrame:
        with duckdb.connect(":memory:") as connection:
            connection.register(table_name, frame)
            return connection.execute(sql).fetchdf()


class SqliteEngine:
    def execute(self, sql: str, frame: pd.DataFrame, table_name: str = "t") -> pd.DataFrame:
        with sqlite3.connect(":memory:") as connection:
            create, insert, rows = _statements(frame, table_name, "?")
            connection.execute(create)
            connection.executemany(insert, rows)
            cursor = connection.execute(sql)
            return pd.DataFrame(
                cursor.fetchall(), columns=[column[0] for column in cursor.description]
            )


class PgEngine:
    def execute(self, sql: str, frame: pd.DataFrame, table_name: str = "t") -> pd.DataFrame:
        with (
            psycopg.connect(os.environ["ROWSETTA_PG_DSN"]) as connection,
            connection.cursor() as cursor,
        ):
            ordinal = "__test_row_ordinal"
            while ordinal in frame.columns:
                ordinal += "_"
            ordered_frame = frame.assign(**{ordinal: range(len(frame))})
            create, insert, rows = _statements(ordered_frame, table_name, "%s")
            cursor.execute(create.encode())
            cursor.executemany(insert.encode(), rows)
            cursor.execute(sql.encode())
            assert cursor.description is not None
            result = pd.DataFrame(
                cursor.fetchall(), columns=[column.name for column in cursor.description]
            )
            return result.sort_values(ordinal).drop(columns=ordinal).reset_index(drop=True)


def _statements(
    frame: pd.DataFrame, table_name: str, placeholder: str
) -> tuple[str, str, list[list[object]]]:
    declarations = ", ".join(
        identifier(column)
        + (" DOUBLE PRECISION" if pd.api.types.is_numeric_dtype(frame[column]) else " TEXT")
        for column in frame.columns
    )
    create = "CREATE TEMP TABLE " + identifier(table_name) + " (" + declarations + ")"
    placeholders = ", ".join([placeholder] * len(frame.columns))
    rows: list[list[object]] = frame.astype(object).where(frame.notna(), None).to_numpy().tolist()
    insert = "".join(("INSERT INTO ", identifier(table_name), " VALUES (", placeholders, ")"))
    return create, insert, rows


def engine(dialect: Dialect) -> SqlEngine:
    if dialect == "duckdb":
        return DuckEngine()
    if dialect == "sqlite":
        return SqliteEngine()
    return PgEngine()


def predictions(frame: pd.DataFrame, target: str = "answer") -> list[str | None]:
    return [None if pd.isna(value) else str(value) for value in frame[f"predicted_{target}"]]


def certificate() -> Certificate:
    coverage = Coverage(8, 10)
    accuracy = Rate(7, 8, 0.5, 0.99, coverage)
    return Certificate(
        tool_name="Rowsetta",
        tool_version="0.1.0",
        export_date=date(2026, 11, 5),
        row_count=10,
        columns=(ColumnType("x", "float64", "DOUBLE", "DOUBLE PRECISION", "REAL"),),
        target="answer",
        classes=("a", "b"),
        tree_depth=1,
        tree_leaves=2,
        in_sample=Count(7, 8, coverage),
        cross_fitted=accuracy,
        rule_accuracy=accuracy,
        teacher_accuracy=accuracy,
        direct_same_accuracy=accuracy,
        direct_tuned_accuracy=accuracy,
        comparison=NoDifference(8),
        abstention_threshold=0.8,
        tabicl_version="2.2.0",
        checkpoint_sha256="b" * 64,
        execution=NotExecuted("browser demo"),
    )
