import hashlib
from typing import Literal, Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rowsetta.core.errors import NotServed
from rowsetta.core.table import SAMPLE_SEED, Table

MIN_CLASSES = 2
MAX_CLASSES = 10


class SourceRef(BaseModel):
    """Fingerprint of the original bytes and the working sample's source row ids."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_name: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: int = Field(ge=0)
    sampled_rows: tuple[int, ...] | None = None
    sample_seed: int = Field(default=SAMPLE_SEED, ge=0)

    @model_validator(mode="after")
    def validate_sample(self) -> Self:
        """Reject ambiguous or out-of-range source row identities."""
        if self.sampled_rows is not None and (
            len(set(self.sampled_rows)) != len(self.sampled_rows)
            or any(row < 0 or row >= self.rows for row in self.sampled_rows)
        ):
            message = "Sampled row ids must be unique and within the source rows."
            raise ValueError(message)
        return self

    @classmethod
    def from_table(cls, file_name: str, data: bytes, table: Table) -> Self:
        """Hash original CSV bytes, retaining sampled ids without reading a file."""
        sampled = (
            tuple(int(row) for row in table.frame.index)
            if len(table.frame) < table.source_rows
            else None
        )
        return cls(
            file_name=file_name,
            sha256=hashlib.sha256(data).hexdigest(),
            rows=table.source_rows,
            sampled_rows=sampled,
        )

    def row_ids(self) -> tuple[int, ...]:
        """Return the working rows in original source coordinates."""
        return self.sampled_rows if self.sampled_rows is not None else tuple(range(self.rows))


class LabelChange(BaseModel):
    """Previous answer needed to undo a label edit after saving and reopening."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["human", "eval"]
    row_id: int = Field(ge=0)
    previous: str | None


class LabelStore(BaseModel):
    """Human training labels and a separate, blind random evaluation sample.

    Call mutation methods to preserve invariants; returned training labels are a copy.
    Served rows remain reserved for evaluation even when their answer is cleared.
    """

    model_config = ConfigDict(extra="forbid")

    human: dict[int, str] = Field(default_factory=dict[int, str])
    eval: dict[int, str] = Field(default_factory=dict[int, str])
    eval_seed: int = Field(default=7, ge=0)
    eval_served: list[int] = Field(default_factory=list[int])
    excluded_columns: frozenset[str] = frozenset()
    classes: tuple[str, ...] = Field(min_length=MIN_CLASSES, max_length=MAX_CLASSES)
    threshold: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    target: str = Field(min_length=1)
    source: SourceRef
    current_eval_row: int | None = None
    undo_history: list[LabelChange] = Field(default_factory=list[LabelChange])

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        """Validate session files before their labels enter the training loop."""
        rows = set(self.source.row_ids())
        served = set(self.eval_served)
        if len(set(self.classes)) != len(self.classes) or any(not label for label in self.classes):
            message = "Classes must be distinct, nonempty names."
            raise ValueError(message)
        if (
            not (set(self.human) | set(self.eval) | served) <= rows
            or len(served) != len(self.eval_served)
            or set(self.human) & served
            or not set(self.eval) <= served
            or (self.current_eval_row is not None and self.current_eval_row not in served)
        ):
            message = "Session rows must belong to the source and keep evaluation separate."
            raise ValueError(message)
        for label in (*self.human.values(), *self.eval.values()):
            self._validate_label(label)
        for change in self.undo_history:
            self._validate_row(change.row_id)
            self._validate_label(change.previous)
            if change.kind == "eval" and change.row_id not in served:
                message = "Undo history must keep evaluation rows separate."
                raise ValueError(message)
        return self

    def set_human(self, row_id: int, label: str | None) -> None:
        """Set or clear a training label on a row outside the evaluation sample."""
        self._validate_row(row_id)
        self._validate_label(label)
        if row_id in self.eval_served:
            raise NotServed
        self._set_label("human", row_id, label)

    def next_eval_row(self) -> int | None:
        """Serve the next eligible row, keeping an unanswered row current."""
        if self.current_eval_row is not None:
            return self.current_eval_row
        for row_id in self.eval_served:
            if row_id not in self.eval:
                self.current_eval_row = row_id
                return row_id
        # Recreating this independent generator makes continuation portable in JSON.
        order = np.random.default_rng(self.eval_seed).permutation(self.source.row_ids())
        unavailable = set(self.human) | set(self.eval_served)
        for candidate in order:
            row_id = int(candidate)
            if row_id not in unavailable:
                self.eval_served.append(row_id)
                self.current_eval_row = row_id
                return row_id
        return None

    def set_eval(self, row_id: int, label: str | None) -> None:
        """Accept only the row currently shown in blind evaluation mode."""
        if row_id != self.current_eval_row:
            raise NotServed
        self._validate_label(label)
        self._set_label("eval", row_id, label)
        if label is not None:
            self.current_eval_row = None

    def undo(self) -> int | None:
        """Revert the most recent edit and reopen an undone evaluation answer."""
        if not self.undo_history:
            return None
        change = self.undo_history.pop()
        labels = self.human if change.kind == "human" else self.eval
        if change.previous is None:
            labels.pop(change.row_id, None)
        else:
            labels[change.row_id] = change.previous
        if change.kind == "eval":
            self.current_eval_row = change.row_id
        elif change.previous is not None and change.row_id in self.eval_served:
            self.eval_served.remove(change.row_id)
            if self.current_eval_row == change.row_id:
                self.current_eval_row = None
        return change.row_id

    def training_rows(self) -> dict[int, str]:
        """Return human labels without exposing the store to training-side edits."""
        return self.human.copy()

    def to_json(self) -> str:
        """Serialize a portable session, including serving and undo state."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> Self:
        """Validate and restore a session without accessing its source file."""
        return cls.model_validate_json(data)

    def _validate_row(self, row_id: int) -> None:
        if row_id not in self.source.row_ids():
            message = "Row id is outside the working sample."
            raise ValueError(message)

    def _validate_label(self, label: str | None) -> None:
        if label is not None and label not in self.classes:
            message = "Label must be one of the session classes."
            raise ValueError(message)

    def _set_label(self, kind: Literal["human", "eval"], row_id: int, label: str | None) -> None:
        labels = self.human if kind == "human" else self.eval
        previous = labels.get(row_id)
        if previous == label:
            return
        self.undo_history.append(LabelChange(kind=kind, row_id=row_id, previous=previous))
        if label is None:
            labels.pop(row_id, None)
        else:
            labels[row_id] = label
