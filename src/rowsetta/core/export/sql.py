"""Portable SQL rules with float32-exact split boundaries."""

import hashlib
import json
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from rowsetta.core.distill import (
    Comparison,
    Count,
    FeatureSpec,
    NoDifference,
    Rate,
    Student,
    TreeClassifier,
    split_condition,
)
from rowsetta.core.errors import UserError

type Dialect = Literal["duckdb", "postgres", "sqlite"]
ONE_HOT_THRESHOLD = 0.5


@dataclass(frozen=True)
class Executed:
    """Identity measured on every source row by the shell."""

    engine_version: str
    identical: int
    total: int


@dataclass(frozen=True)
class NotExecuted:
    """An explicit reason that execution identity has not been checked."""

    reason: str


@dataclass(frozen=True)
class ColumnType:
    """Source schema and the required storage types for each SQL engine."""

    name: str
    source_type: str
    duckdb: str
    postgres: str
    sqlite: str


@dataclass(frozen=True)
class Certificate:
    """Export facts supplied by the caller, without clock or model access."""

    tool_name: str
    tool_version: str
    export_date: date
    row_count: int
    columns: tuple[ColumnType, ...]
    target: str
    classes: tuple[str, ...]
    tree_depth: int
    tree_leaves: int
    in_sample: Count
    cross_fitted: Rate
    rule_accuracy: Rate
    teacher_accuracy: Rate
    direct_same_accuracy: Rate
    direct_tuned_accuracy: Rate
    comparison: Comparison
    abstention_threshold: float
    tabicl_version: str
    checkpoint_sha256: str
    execution: Executed | NotExecuted

    @property
    def schema_sha256(self) -> str:
        """Hash ordered column names and source types as compact UTF-8 JSON."""
        schema = [(column.name, column.source_type) for column in self.columns]
        encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def header(self) -> str:
        """Render facts as SQL comments, including untrusted multiline names."""
        verdict = (
            (
                f"no difference ({self.comparison.n} jointly answered)"
                if self.comparison.n
                else "not measured (0 jointly answered)"
            )
            if isinstance(self.comparison, NoDifference)
            else f"{self.comparison.kind}, p={self.comparison.p:.6g}"
        )
        execution = (
            f"DuckDB {self.execution.engine_version}: "
            f"{self.execution.identical}/{self.execution.total} rows identical"
            if isinstance(self.execution, Executed)
            else f"not executed ({self.execution.reason})"
        )
        lines = [
            f"{self.tool_name} {self.tool_version}",
            f"Export date: {self.export_date.isoformat()}",
            f"Dataset rows: {self.row_count}",
            f"Schema SHA-256: {self.schema_sha256}",
            *(
                f"Column {column.name!r} ({column.source_type}): "
                f"DuckDB {column.duckdb}; PostgreSQL {column.postgres}; SQLite {column.sqlite}"
                for column in self.columns
            ),
            f"Target: {self.target}",
            f"Classes: {json.dumps(self.classes, ensure_ascii=False)}",
            f"Tree: depth {self.tree_depth}, {self.tree_leaves} leaves",
            _measurement("In-sample agreement", self.in_sample),
            _measurement("Cross-fitted agreement", self.cross_fitted),
            _measurement(
                "Rule conditional evaluation accuracy (answered rows)", self.rule_accuracy
            ),
            _measurement(
                "Teacher conditional evaluation accuracy (confident predictions)",
                self.teacher_accuracy,
            ),
            _measurement("Direct tree, same settings", self.direct_same_accuracy),
            _measurement("Direct tree, tuned", self.direct_tuned_accuracy),
            f"McNemar (rule versus tuned direct tree): {verdict}",
            f"Abstention threshold: {self.abstention_threshold}",
            f"tabicl version: {self.tabicl_version}",
            f"Checkpoint SHA-256: {self.checkpoint_sha256}",
            f"Execution: {execution}",
        ]
        return "\n".join("-- " + part for line in lines for part in line.splitlines()) + "\n"


def _measurement(name: str, count: Count | Rate) -> str:
    coverage = count.coverage
    interval = f"; 95% interval [{count.lo:.4f}, {count.hi:.4f}]" if isinstance(count, Rate) else ""
    return f"{name}: {count.k}/{count.n}; coverage {coverage.answered}/{coverage.total}{interval}"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _literal(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class SqlOptions:
    """Optional source naming, leaf overrides and certificate facts."""

    table_name: str = "t"
    leaf_labels: Sequence[str | None] | None = None
    certificate: Certificate | None = None


class UnsupportedDatetimeSplitError(UserError):
    """A used datetime feature has no portable SQL representation."""

    def __init__(self, column: str) -> None:
        self.column = column
        super().__init__(
            f"SQL export does not support datetime splits on column {column!r}.",
            shlex.join(["rowsetta", "open", "data.csv"])
            + f"; exclude column {column!r} and re-teach without it before exporting.",
        )


def _split_sql(column: str, operator: str, literal: str) -> str:
    name = _identifier(column)
    if operator in ("IS NULL", "IS NOT NULL"):
        return f"{name} {operator}"
    if operator.startswith("IS NULL OR "):
        return f"({name} IS NULL OR {name} {operator.rsplit(maxsplit=1)[-1]} {literal})"
    return f"{name} {operator.rsplit(maxsplit=1)[-1]} {literal}"


def tree_to_sql(
    tree: TreeClassifier,
    *,
    feature_spec: FeatureSpec,
    target: str,
    dialect: Dialect,
    options: SqlOptions | None = None,
) -> str:
    """Export a fitted single-output classifier, with labels in leaf traversal order.

    Numeric source columns must retain float64 precision; missing cells are SQL
    NULL. One-hot inputs use their original string columns, including unseen values.
    """
    options = options or SqlOptions()
    table_name = options.table_name
    leaf_labels = options.leaf_labels
    certificate = options.certificate
    if dialect not in ("duckdb", "postgres", "sqlite"):
        message = f"Unsupported SQL dialect: {dialect}"
        raise ValueError(message)
    structure = tree.tree_
    if structure.value.shape[1] != 1:
        message = "SQL export requires a single-output classification tree."
        raise ValueError(message)
    if leaf_labels is not None and len(leaf_labels) != tree.get_n_leaves():
        message = "Supply one label per leaf in left-to-right order."
        raise ValueError(message)
    if certificate is not None and certificate.target != target:
        message = "The certificate target must match the exported target."
        raise ValueError(message)
    labels = iter(leaf_labels) if leaf_labels is not None else None

    def visit(node: int) -> tuple[str, str]:
        left = int(structure.children_left[node])
        if left == -1:
            values = structure.value[node, 0]
            label = next(labels) if labels is not None else str(tree.classes_[int(values.argmax())])
            return _literal(label), f"{float(values.max() / values.sum()):.4f}"
        feature = feature_spec.features[int(structure.feature[node])]
        if feature.kind == "datetime":
            raise UnsupportedDatetimeSplitError(feature.column)
        if feature.kind == "categorical" and structure.threshold[node] != ONE_HOT_THRESHOLD:
            message = "Categorical features must be one-hot encoded with a 0.5 split."
            raise ValueError(message)
        column, operator, literal = split_condition(
            feature,
            float(structure.threshold[node]),
            left=True,
            missing_left=bool(structure.missing_go_to_left[node]),
        )
        condition = _split_sql(column, operator, literal)
        left_values = visit(left)
        right_values = visit(int(structure.children_right[node]))
        return (
            f"CASE WHEN {condition} THEN {left_values[0]} ELSE {right_values[0]} END",
            f"CASE WHEN {condition} THEN {left_values[1]} ELSE {right_values[1]} END",
        )

    prediction, confidence = visit(0)
    confidence = f"CAST({confidence} AS DOUBLE PRECISION)" if dialect == "postgres" else confidence
    header = certificate.header() if certificate is not None else ""
    return "".join(
        (
            header,
            "SELECT *, ",
            prediction,
            " AS ",
            _identifier("predicted_" + target),
            ", ",
            confidence,
            " AS ",
            _identifier("predicted_" + target + "_confidence"),
            " FROM ",
            _identifier(table_name),
            ";\n",
        )
    )


def to_sql(
    student: Student,
    *,
    dialect: Dialect,
    table_name: str = "t",
    certificate: Certificate,
) -> str:
    """Export a student's abstaining leaves and the caller's measured certificate."""
    return tree_to_sql(
        student.tree,
        feature_spec=student.feature_spec,
        target=certificate.target,
        dialect=dialect,
        options=SqlOptions(
            table_name=table_name,
            leaf_labels=_student_leaf_labels(student),
            certificate=certificate,
        ),
    )


def _student_leaf_labels(student: Student) -> list[str | None]:
    structure = student.tree.tree_

    def visit(node: int) -> list[str | None]:
        left = int(structure.children_left[node])
        if left == -1:
            return [student.leaf_label(node)]
        return visit(left) + visit(int(structure.children_right[node]))

    return visit(0)
