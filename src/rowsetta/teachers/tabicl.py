import importlib
import os
from typing import Protocol

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from rowsetta.core.teacher import TEACHER_N_ESTIMATORS
from rowsetta.teachers.checkpoint import checkpoint_path


class Classifier(Protocol):
    """The fitted sklearn surface used by the adapter."""

    classes_: NDArray[np.str_]

    def fit(self, x: pd.DataFrame, y: pd.Series) -> object:
        """Fit the model's in-context training set."""
        ...

    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Return probabilities in classes_ order."""
        ...


class TabICLTeacher:
    """Local TabICLv2 with revision-pinned, verified weights and a KV cache."""

    def __init__(self, *, device: str | None = None) -> None:
        self.classes: tuple[str, ...] = ()
        module = importlib.import_module("tabicl")
        self._classifier: Classifier = module.TabICLClassifier(
            n_estimators=TEACHER_N_ESTIMATORS,
            kv_cache=True,
            device=device if device is not None else os.environ.get("ROWSETTA_DEVICE"),
            model_path=checkpoint_path(),
            allow_auto_download=False,
            random_state=7,
            verbose=False,
        )

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        """Fit only supplied training rows, exposing upstream probability order."""
        self._classifier.fit(x, y)
        self.classes = tuple(str(label) for label in self._classifier.classes_)

    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Return local model probabilities without relabelling their columns."""
        return np.asarray(self._classifier.predict_proba(x), dtype=np.float64)
