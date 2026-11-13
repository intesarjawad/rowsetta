import importlib
import os
import sqlite3

import duckdb
import pandas as pd
from pydantic import JsonValue

from rowsetta.core.distill import Student, leaf_summary
from rowsetta.core.export.sql import SqlOptions, tree_to_sql


def identity(student: Student, target: str) -> dict[str, JsonValue]:
    """Execute the abstaining student on the same rows in available SQL engines."""
    expected = student.predict(student.frame)
    labels = [line.label for line in leaf_summary(student, student.frame.iloc[:0])]
    results: dict[str, JsonValue] = {}
    with duckdb.connect(":memory:") as connection:
        connection.register("t", student.frame)
        sql = tree_to_sql(
            student.tree,
            feature_spec=student.feature_spec,
            target=target,
            dialect="duckdb",
            options=SqlOptions(leaf_labels=labels),
        )
        actual = connection.execute(sql).fetchdf()[f"predicted_{target}"].tolist()
        results["duckdb"] = match_counts(expected, actual, require_exact=True)
    with sqlite3.connect(":memory:") as connection:
        importlib.import_module("pandas.io.sql").to_sql(student.frame, "t", connection, index=False)
        sql = tree_to_sql(
            student.tree,
            feature_spec=student.feature_spec,
            target=target,
            dialect="sqlite",
            options=SqlOptions(leaf_labels=labels),
        )
        cursor = connection.execute(sql)
        index = [column[0] for column in cursor.description].index(f"predicted_{target}")
        actual = [row[index] for row in cursor.fetchall()]
        results["sqlite"] = match_counts(expected, actual, require_exact=True)
    if os.environ.get("ROWSETTA_PG_DSN"):
        results["postgres"] = postgres_identity(student, target, expected, labels)
    else:
        results["postgres"] = {"status": "not executed: set ROWSETTA_PG_DSN", "rows_checked": 0}
    results["orbital"] = orbital_identity(student)
    return results


def match_counts(
    expected: list[str | None], actual: list[object], *, require_exact: bool = False
) -> dict[str, JsonValue]:
    """Preserve mismatches as measurements rather than rounding identity rates."""
    normalized = [
        None if missing else str(value)
        for value, missing in zip(actual, pd.Series(actual).isna().tolist(), strict=True)
    ]
    matches = sum(a == b for a, b in zip(expected, normalized, strict=True))
    if require_exact and matches != len(expected):
        message = f"SQL identity failed: {matches} of {len(expected)} predictions match the rule."
        raise ValueError(message)
    return {
        "identical": matches,
        "rows_checked": len(expected),
        "identity_rate": matches / len(expected),
    }


def postgres_identity(
    student: Student, target: str, expected: list[str | None], labels: list[str | None]
) -> dict[str, JsonValue]:
    """Use a transaction-local table so a configured database retains no benchmark data."""
    psycopg = importlib.import_module("psycopg")
    sql_module = importlib.import_module("psycopg.sql")
    columns = [str(column) for column in student.frame.columns]
    types = [
        "DOUBLE PRECISION" if pd.api.types.is_numeric_dtype(student.frame[column]) else "TEXT"
        for column in columns
    ]
    with psycopg.connect(os.environ["ROWSETTA_PG_DSN"]) as connection:
        definitions = sql_module.SQL(", ").join(
            sql_module.SQL("{} {}").format(sql_module.Identifier(column), sql_module.SQL(kind))
            for column, kind in zip(columns, types, strict=True)
        )
        connection.execute(
            sql_module.SQL("CREATE TEMP TABLE t ({}) ON COMMIT DROP").format(definitions)
        )
        with connection.cursor().copy("COPY t FROM STDIN") as copy:
            for row in student.frame.itertuples(index=False, name=None):
                copy.write_row(tuple(None if pd.isna(value) else value for value in row))
        sql = tree_to_sql(
            student.tree,
            feature_spec=student.feature_spec,
            target=target,
            dialect="postgres",
            options=SqlOptions(leaf_labels=labels),
        )
        cursor = connection.execute(sql)
        description = cursor.description
        if description is None:
            message = "PostgreSQL returned no prediction columns."
            raise ValueError(message)
        index = [column.name for column in description].index(f"predicted_{target}")
        return match_counts(expected, [row[index] for row in cursor.fetchall()], require_exact=True)


def orbital_identity(student: Student) -> dict[str, JsonValue]:
    """Measure the upstream SQL converter on the student's encoded numeric features."""
    try:
        orbital = importlib.import_module("orbital")
    except ModuleNotFoundError:
        return {"status": "unsupported: install the pinned bench dependency group"}
    pipeline = importlib.import_module("sklearn.pipeline").Pipeline([("tree", student.tree)])
    names = [f"x{i}" for i in range(len(student.feature_spec.features))]
    frame = pd.DataFrame(student.feature_spec.transform(student.frame), columns=names)
    try:
        parsed = orbital.parse_pipeline(
            pipeline, features={name: orbital.types.DoubleColumnType() for name in names}
        )
        sql = orbital.export_sql("t", parsed, dialect="duckdb")
        with duckdb.connect(":memory:") as connection:
            connection.register("t", frame)
            actual = connection.execute(sql).fetchdf().iloc[:, 0].tolist()
    except (NotImplementedError, ValueError, TypeError, KeyError, duckdb.Error) as error:
        return {"status": f"unsupported: {type(error).__name__}: {error}"}
    return {
        **match_counts(student.predict(student.frame), actual),
        "inputs": "encoded features; abstention is part of the reference rule",
    }
