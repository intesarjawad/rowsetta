import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from rowsetta.core.errors import UserError
from rowsetta.core.features import teacher_frame
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table
from rowsetta.core.teacher import Teacher

if TYPE_CHECKING:
    from collections.abc import Iterator

    import numpy as np
    from numpy.typing import NDArray

AUDIT_FOLDS = 5
AUDIT_SEED = 7
# Preload before request/refit threads can race sklearn's first transitive imports.
MODEL_SELECTION = importlib.import_module("sklearn.model_selection")


class NeedAuditLabelsError(UserError):
    """Out-of-fold scoring needs every class in every training fold."""

    def __init__(self, missing: dict[str, int]) -> None:
        self.missing = missing
        needed = "; ".join(
            f"{count} more {'row' if count == 1 else 'rows'} of: {label}"
            for label, count in missing.items()
        )
        super().__init__(
            f"Checking labels starts once every class has {AUDIT_FOLDS} labels.",
            f"rowsetta demo; label {needed}",
        )


@dataclass(frozen=True)
class Suspect:
    """A human label and the out-of-fold teacher probability of that label."""

    row_id: int
    given: str
    given_probability: float
    likely: str


def audit_labels(teacher: Teacher, table: Table, store: LabelStore) -> list[Suspect]:
    """Rank human labels from least to most plausible by out-of-fold probability.

    This is the self-confidence ranking of confident learning (Northcutt, Jiang and
    Chuang 2021). Each fold refits the teacher on the other folds only, so no row is
    ever in its own context. Evaluation labels are neither fitted nor ranked.
    """
    human = store.training_rows()
    rows = sorted(human)
    labels = pd.Series([human[row] for row in rows], index=rows, dtype=object)
    counts = labels.value_counts()
    missing = {
        label: AUDIT_FOLDS - int(counts.get(label, 0))
        for label in store.classes
        if counts.get(label, 0) < AUDIT_FOLDS
    }
    if missing:
        raise NeedAuditLabelsError(missing)
    frame = teacher_frame(table, store).frame.loc[rows]
    splits: Iterator[tuple[NDArray[np.intp], NDArray[np.intp]]] = MODEL_SELECTION.StratifiedKFold(
        n_splits=AUDIT_FOLDS, shuffle=True, random_state=AUDIT_SEED
    ).split(frame, labels)
    given = [0.0] * len(rows)
    likely = [""] * len(rows)
    for train, held_out in splits:
        teacher.fit(frame.iloc[train], labels.iloc[train])
        if set(teacher.classes) != set(store.classes):
            message = "Fitted teacher classes must match session classes."
            raise ValueError(message)
        proba = teacher.predict_proba(frame.iloc[held_out])
        for position, row in zip(held_out.tolist(), proba, strict=True):
            given[position] = float(row[teacher.classes.index(human[rows[position]])])
            likely[position] = teacher.classes[int(row.argmax())]
    return [
        Suspect(rows[position], human[rows[position]], given[position], likely[position])
        for position in sorted(range(len(rows)), key=given.__getitem__)
    ]
