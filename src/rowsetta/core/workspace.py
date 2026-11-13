from dataclasses import dataclass, replace
from datetime import date
from typing import Literal, Protocol

import numpy as np

from rowsetta.core.active import Predictions, next_row
from rowsetta.core.distill import (
    InsufficientFoldSupportError,
    Student,
    compare_on_eval,
    direct_trees,
    eval_accuracy,
    fidelity_cross_fitted,
    fidelity_in_sample,
    fit_student,
    teacher_eval_accuracy,
)
from rowsetta.core.errors import (
    BadCsvError,
    FileTooLargeError,
    NeedLabelsError,
    TooManyColumnsError,
    UnknownColumnsError,
    WorkspaceError,
)
from rowsetta.core.evaluation import EvalResult, evaluate
from rowsetta.core.export.sql import Certificate, ColumnType, NotExecuted
from rowsetta.core.features import TeacherFrame, teacher_frame
from rowsetta.core.session import MAX_CLASSES, MIN_CLASSES, LabelStore, SourceRef
from rowsetta.core.table import MAX_FILE_BYTES, Table, load_csv
from rowsetta.core.teacher import MIN_LABELS_PER_CLASS, Proposals, Teacher, predict_table

__all__ = [
    "DEFAULT_THRESHOLD",
    "ExportMetadata",
    "LabelStore",
    "Proposals",
    "SourceRef",
    "Table",
    "Teacher",
    "TeacherFrame",
    "Workspace",
    "load_csv",
    "predict_table",
    "teacher_frame",
]

# Proposals below this confidence render as unsure until the user moves the slider.
DEFAULT_THRESHOLD = 0.60


@dataclass(frozen=True)
class ExportMetadata:
    """Shell-supplied provenance, keeping clock and package lookups out of core."""

    export_date: date
    tool_version: str
    teacher_version: str
    checkpoint_sha256: str


class SessionPersistence(Protocol):
    """Injected session I/O for local shells; browser workspaces stay in memory."""

    def open(self, data: bytes, source: SourceRef) -> tuple[LabelStore | None, str | None]:
        """Resolve the dataset and restore only a matching session."""
        ...

    def save(self, store: LabelStore) -> None:
        """Persist a complete session mutation."""
        ...


class Workspace:
    """Own one table and invalidate derived results whenever session inputs change."""

    def __init__(
        self, persistence: SessionPersistence | None = None, *, max_bytes: int = MAX_FILE_BYTES
    ) -> None:
        self.persistence = persistence
        self.max_bytes = max_bytes
        self.notice: str | None = None
        self.table: Table | None = None
        self.source: SourceRef | None = None
        self.data = b""
        self.store: LabelStore | None = None
        self.proposals: Proposals | None = None
        self.student: Student | None = None
        self.generation = 0

    def load(
        self,
        data: bytes,
        file_name: str,
        *,
        max_rows: int,
        columns: tuple[str, ...] | None = None,
        display_name: str | None = None,
    ) -> None:
        """Replace the table only after CSV validation succeeds.

        Errors name the file `display_name` when given, such as a path typed on the command
        line, so their recovery command runs from the same place.
        """
        shown = display_name or file_name
        try:
            table = load_csv(
                data, max_rows=max_rows, max_bytes=self.max_bytes, keep_columns=columns
            )
        except BadCsvError as error:
            raise BadCsvError(error.reason, error.line_number, file_name=shown) from error
        except FileTooLargeError as error:
            raise FileTooLargeError(error.size_bytes, error.max_bytes, file_name=shown) from error
        except TooManyColumnsError as error:
            raise TooManyColumnsError(
                error.column_names,
                error.max_columns,
                file_name=shown,
            ) from error
        except UnknownColumnsError as error:
            raise UnknownColumnsError(
                error.unknown, error.column_names, error.max_columns, file_name=shown
            ) from error
        source = SourceRef.from_table(file_name, data, table)
        store, notice = self.persistence.open(data, source) if self.persistence else (None, None)
        if store is not None:
            self._require_features(table, store)
        self.source, self.notice = source, notice
        self.table, self.data, self.store = table, data, store
        self.invalidate()

    def set_target(self, target: str, classes: tuple[str, ...]) -> None:
        """Start an empty label store; a name that is not a column creates a new one.

        Values already in a column of that name never become training labels here.
        """
        self._start(
            LabelStore(
                target=target,
                classes=classes,
                source=self._require_source(),
                threshold=DEFAULT_THRESHOLD,
            )
        )

    def set_target_from_column(self, column: str) -> None:
        """Take classes and human labels from a column; rows missing a value stay unlabelled."""
        table = self.require_table()
        if column not in table.frame:
            msg = f"The column `{column}` does not exist."
            raise WorkspaceError(
                msg,
                "Choose one of the table's columns, or name a new target and its classes.",
                status_code=422,
            )
        values = table.frame[column].dropna().astype(str)
        classes = tuple(sorted(values.unique()))
        if not MIN_CLASSES <= len(classes) <= MAX_CLASSES:
            msg = (
                f"`{column}` has {len(classes)} distinct values; "
                f"a target needs {MIN_CLASSES} to {MAX_CLASSES}."
            )
            raise WorkspaceError(
                msg,
                f"Choose a column with {MIN_CLASSES} to {MAX_CLASSES} values, "
                "or name a new target and its classes.",
                status_code=422,
            )
        human = dict(zip(values.index.tolist(), values.tolist(), strict=True))
        self._start(
            LabelStore(
                target=column,
                classes=classes,
                source=self._require_source(),
                human=human,
                threshold=DEFAULT_THRESHOLD,
            )
        )

    def _require_source(self) -> SourceRef:
        self.require_table()
        if self.source is None:
            msg = "Load a CSV before selecting a target."
            raise WorkspaceError(msg)
        return self.source

    def _start(self, store: LabelStore) -> None:
        self._require_features(self.require_table(), store)
        self.store = store
        self.invalidate()

    def set_label(self, row: int, label: str | None, mode: Literal["human", "eval"]) -> None:
        """Validate an edit and keep evaluation rows out of human training."""
        store = self.require_store()
        if row not in store.source.row_ids() or (label is not None and label not in store.classes):
            msg = "Use a source row id and one of the configured classes."
            raise WorkspaceError(msg, status_code=422)
        if mode == "human":
            store.set_human(row, label)
        else:
            store.set_eval(row, label)
        self.invalidate()

    def undo(self) -> int | None:
        """Undo through the store and discard predictions based on the reverted edit."""
        row = self.require_store().undo()
        self.invalidate()
        return row

    def next_eval(self) -> int | None:
        """Reserve a random row before exposing it for blind evaluation."""
        store = self.require_store()
        before = (tuple(store.eval_served), store.current_eval_row)
        row = store.next_eval_row()
        if before != (tuple(store.eval_served), store.current_eval_row):
            self.student = None
            if self.persistence is not None:
                self.persistence.save(store)
        return row

    def exclude(self, name: str, *, excluded: bool) -> None:
        """Reject exclusions that would leave the model without usable features."""
        table, store = self.require_table(), self.require_store()
        if name not in table.frame or name == store.target:
            msg = "Choose a feature column to exclude."
            raise WorkspaceError(msg, status_code=422)
        columns = store.excluded_columns | {name} if excluded else store.excluded_columns - {name}
        candidate = store.model_copy(update={"excluded_columns": frozenset(columns)})
        self._require_features(table, candidate)
        store.excluded_columns = frozenset(columns)
        self.invalidate()

    def set_threshold(self, threshold: float) -> None:
        """Invalidate teacher abstention and the rule together."""
        self.require_store().threshold = threshold
        self.invalidate()

    def invalidate(self) -> None:
        """Supersede in-flight generations and discard stale derived data."""
        self.generation += 1
        self.proposals = None
        self.student = None
        if self.persistence is not None and self.store is not None:
            self.persistence.save(self.store)

    def missing_labels(self) -> dict[str, int]:
        """Return the human labels still needed before proposals can start."""
        store = self.require_store()
        labels = list(store.human.values())
        return {
            label: MIN_LABELS_PER_CLASS - labels.count(label)
            for label in store.classes
            if labels.count(label) < MIN_LABELS_PER_CLASS
        }

    def publish(self, proposals: Proposals, generation: int) -> bool:
        """Accept predictions only if no newer edit has superseded their inputs."""
        if generation != self.generation:
            return False
        self.proposals = replace(proposals, generation=generation)
        return True

    def require_table(self) -> Table:
        """Require loaded data at the orchestration boundary."""
        if self.table is None:
            msg = "No CSV is loaded."
            raise WorkspaceError(msg)
        return self.table

    def require_store(self) -> LabelStore:
        """Require an explicit target and class vocabulary before labelling."""
        if self.store is None:
            msg = "Choose a target and its classes first."
            raise WorkspaceError(msg)
        return self.store

    def require_proposals(self) -> Proposals:
        """Distinguish missing human labels from an unfinished refit."""
        missing = self.missing_labels()
        if missing:
            raise NeedLabelsError(missing)
        if self.proposals is None:
            msg = "The latest refit has not finished."
            raise WorkspaceError(msg)
        return self.proposals

    def distill(self, max_depth: int) -> Student:
        """Fit a rule using current proposals and human labels, reserving eval rows."""
        self.student = fit_student(
            self.require_table(),
            self.require_store(),
            self.require_proposals(),
            max_depth=max_depth,
        )
        return self.student

    def next_human(self) -> int | None:
        """Select an eligible row without letting active selection touch eval rows."""
        store = self.require_store()
        rows = [
            row
            for row in store.source.row_ids()
            if row not in store.human and row not in store.eval_served
        ]
        if not rows:
            return None
        if self.proposals is None:
            return rows[0]
        probabilities = self.proposals.proba
        return next_row(
            Predictions(
                probabilities.to_numpy(), list(probabilities.index), tuple(probabilities.columns)
            ),
            store,
            pick_index=len(store.human),
            rng=np.random.default_rng(store.eval_seed),
        )

    def evaluation(self) -> EvalResult | None:
        """Measure raw teacher answers independently of the display threshold."""
        if self.store is None or self.proposals is None:
            return None
        raw_labels = dict(self.proposals.label)
        for row in self.store.eval:
            raw_labels[row] = str(self.proposals.proba.loc[row].idxmax())
        return evaluate(self.store, replace(self.proposals, label=raw_labels))

    def certificate(self, metadata: ExportMetadata) -> Certificate:
        """Measure the current rule without inventing missing evaluation evidence."""
        table, store, proposals = (
            self.require_table(),
            self.require_store(),
            self.require_proposals(),
        )
        student = self.student
        if student is None:
            msg = "Distil the current rule before exporting."
            raise WorkspaceError(msg)
        try:
            cross_fitted = fidelity_cross_fitted(student, store, proposals)
            direct = direct_trees(table, store, settings=student.settings)
        except InsufficientFoldSupportError as error:
            raise WorkspaceError(error.what, error.next_step) from error
        columns = tuple(
            _column_type(name, str(table.frame[name].dtype)) for name in table.frame.columns
        )
        return Certificate(
            tool_name="Rowsetta",
            tool_version=metadata.tool_version,
            export_date=metadata.export_date,
            row_count=table.source_rows,
            columns=columns,
            target=store.target,
            classes=store.classes,
            tree_depth=student.tree.get_depth(),
            tree_leaves=student.tree.get_n_leaves(),
            in_sample=fidelity_in_sample(student, store, proposals),
            cross_fitted=cross_fitted,
            rule_accuracy=eval_accuracy(student, store),
            teacher_accuracy=teacher_eval_accuracy(proposals, store),
            direct_same_accuracy=direct.same_settings.accuracy,
            direct_tuned_accuracy=direct.tuned.accuracy,
            comparison=compare_on_eval(student, direct.tuned.student, store),
            abstention_threshold=store.threshold,
            tabicl_version=metadata.teacher_version,
            checkpoint_sha256=metadata.checkpoint_sha256,
            execution=NotExecuted("verification pending"),
        )

    @staticmethod
    def _require_features(table: Table, store: LabelStore) -> None:
        try:
            teacher_frame(table, store)
        except ValueError as error:
            raise WorkspaceError(str(error), status_code=422) from error


def _column_type(name: str, source_type: str) -> ColumnType:
    if source_type.startswith(("int", "uint", "float")):
        return ColumnType(name, source_type, "DOUBLE", "DOUBLE PRECISION", "REAL")
    return ColumnType(name, source_type, "VARCHAR", "TEXT", "TEXT")
