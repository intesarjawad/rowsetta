from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from rowsetta.core.features import teacher_frame
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table

TEACHER_N_ESTIMATORS = 4
MIN_LABELS_PER_CLASS = 2
DEFAULT_BATCH_ROWS = 2_000
PROBABILITY_TOLERANCE = 1e-5  # Float32 model probabilities may not sum to exactly one.


class Teacher(Protocol):
    """Fitted probability columns follow classes, independently of session order."""

    classes: tuple[str, ...]

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        """Fit using human training rows only."""
        ...

    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Return an (n_rows, n_classes) probability matrix."""
        ...


@dataclass(frozen=True)
class Proposals:
    """Source-indexed predictions; human rows have labels but no probabilities.

    Evaluation predictions are retained for accuracy only. Presentation callers
    must hide every row in LabelStore.eval_served during blind evaluation.
    """

    label: dict[int, str]
    confidence: dict[int, float]
    proba: pd.DataFrame
    abstained: frozenset[int]
    generation: int


def proposals_from_proba(
    proba: NDArray[np.float64], classes: tuple[str, ...], store: LabelStore, *, generation: int
) -> Proposals:
    """Validate model output and preserve human answers without changing the store."""
    rows = store.source.row_ids()
    if (
        len(set(classes)) != len(classes)
        or set(classes) != set(store.classes)
        or proba.shape != (len(rows), len(classes))
    ):
        message = "Model probabilities must match source rows and session classes."
        raise ValueError(message)
    if (
        not np.isfinite(proba).all()
        or (proba < 0).any()
        or (proba > 1).any()
        or not np.allclose(proba.sum(axis=1), 1, atol=PROBABILITY_TOLERANCE, rtol=0)
    ):
        message = "Model probabilities must be finite, within [0, 1] and sum to one."
        raise ValueError(message)
    probabilities = pd.DataFrame(proba.copy(), index=list(rows), columns=list(classes))
    labels = store.training_rows()
    confidence: dict[int, float] = {}
    abstained: set[int] = set()
    for position, row_id in enumerate(rows):
        if row_id in labels:
            probabilities.loc[row_id] = np.nan
        else:
            winner = int(proba[position].argmax())
            confidence[row_id] = float(proba[position, winner])
            if confidence[row_id] < store.threshold:
                labels[row_id] = "unsure"
                abstained.add(row_id)
            else:
                labels[row_id] = classes[winner]
    return Proposals(labels, confidence, probabilities, frozenset(abstained), generation)


def predict_table(
    teacher: Teacher,
    table: Table,
    store: LabelStore,
    *,
    batch_rows: int = DEFAULT_BATCH_ROWS,
    on_progress: Callable[[int, int], None] | None = None,
) -> Proposals:
    """Fit human labels and predict remaining rows in bounded batches.

    Progress counts predicted rows, including reserved evaluation rows.
    """
    if batch_rows <= 0:
        message = "batch_rows must be positive."
        raise ValueError(message)
    labels = store.training_rows()
    if any(list(labels.values()).count(label) < MIN_LABELS_PER_CLASS for label in store.classes):
        message = f"Label at least {MIN_LABELS_PER_CLASS} rows per class before fitting."
        raise ValueError(message)
    frame = teacher_frame(table, store).frame.loc[list(store.source.row_ids())]
    train_rows = list(labels)
    teacher.fit(frame.loc[train_rows], pd.Series(labels).loc[train_rows])
    if set(teacher.classes) != set(store.classes):
        message = "Fitted teacher classes must match session classes."
        raise ValueError(message)
    pending = [position for position, row in enumerate(frame.index) if row not in labels]
    proba = np.full((len(frame), len(teacher.classes)), 1 / len(teacher.classes))
    if on_progress is not None:
        on_progress(0, len(pending))
    for start in range(0, len(pending), batch_rows):
        positions = pending[start : start + batch_rows]
        batch = teacher.predict_proba(frame.iloc[positions])
        if batch.shape != (len(positions), len(teacher.classes)):
            message = "Model probabilities have an unexpected batch shape."
            raise ValueError(message)
        proba[positions] = batch
        if on_progress is not None:
            on_progress(start + len(positions), len(pending))
    return proposals_from_proba(proba, teacher.classes, store, generation=0)
