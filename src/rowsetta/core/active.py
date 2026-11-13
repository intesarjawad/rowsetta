from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from rowsetta.core.session import LabelStore

MIN_HUMAN_PER_CLASS = 3
RANDOM_PICK_PERIOD = 5


@dataclass(frozen=True)
class Predictions:
    """Teacher probabilities for source rows in class order."""

    proba: NDArray[np.float64]
    row_ids: Sequence[int]
    classes: tuple[str, ...]


def next_row(
    predictions: Predictions,
    store: LabelStore,
    *,
    pick_index: int,
    rng: np.random.Generator,
) -> int:
    """Select a source row, prioritizing class support before exploration and margin.

    Probability columns follow classes. Ties follow class order, then row order;
    previously served evaluation rows remain reserved after clearing an answer.
    Raises ValueError when no eligible row remains.
    """
    proba, row_ids, classes = predictions.proba, predictions.row_ids, predictions.classes
    if proba.shape != (len(row_ids), len(classes)) or set(classes) != set(store.classes):
        message = "Probability dimensions must match row ids and session classes."
        raise ValueError(message)
    unavailable = set(store.human) | set(store.eval) | set(store.eval_served)
    if store.current_eval_row is not None:
        unavailable.add(store.current_eval_row)
    positions = [position for position, row in enumerate(row_ids) if row not in unavailable]
    if not positions:
        message = "No unlabelled rows remain outside the evaluation sample."
        raise ValueError(message)
    candidates = proba[positions]
    counts = Counter(store.human.values())
    for column, label in enumerate(classes):
        if counts[label] < MIN_HUMAN_PER_CLASS:
            return row_ids[positions[int(candidates[:, column].argmax())]]
    if pick_index % RANDOM_PICK_PERIOD == RANDOM_PICK_PERIOD - 1:
        return row_ids[int(rng.choice(positions))]
    ordered = np.sort(candidates, axis=1)
    margins = ordered[:, -1] - ordered[:, -2]
    return row_ids[positions[int(margins.argmin())]]
