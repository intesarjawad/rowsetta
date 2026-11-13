import importlib
from typing import Protocol

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pandas.api.types import is_numeric_dtype

LITE_TREES = 200
LITE_SEED = 7


class Forest(Protocol):
    """The forest's probability surface, without relying on unavailable sklearn stubs."""

    def fit(self, x: NDArray[np.float64], y: pd.Series) -> object:
        """Fit encoded human labels."""
        ...

    def predict_proba(self, x: NDArray[np.float64]) -> NDArray[np.float64]:
        """Return probabilities in sorted class order."""
        ...


class Encoder(Protocol):
    """Training-only category mapping used by the lite teacher."""

    def fit_transform(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Learn categories and encode the training frame."""
        ...

    def transform(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Encode with the training categories."""
        ...


class LiteTeacher:
    """Browser fallback: deterministic random forest with native missing-value routing."""

    def __init__(self) -> None:
        self.classes: tuple[str, ...] = ()
        self._categorical: list[str] = []
        self._encoder: Encoder = importlib.import_module("sklearn.preprocessing").OrdinalEncoder(
            handle_unknown="use_encoded_value", unknown_value=np.nan
        )
        self._forest: Forest = importlib.import_module("sklearn.ensemble").RandomForestClassifier(
            n_estimators=LITE_TREES, min_samples_leaf=1, random_state=LITE_SEED, n_jobs=1
        )

    def _matrix(self, x: pd.DataFrame, *, fit: bool = False) -> NDArray[np.float64]:
        frame = x.copy()
        if self._categorical:
            categories = frame[self._categorical].fillna(np.nan)
            values = (
                self._encoder.fit_transform(categories)
                if fit
                else self._encoder.transform(categories)
            )
            frame[self._categorical] = values
        return frame.to_numpy(dtype=np.float64)

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        """Fit category mappings and trees using human training rows only."""
        self._categorical = [str(name) for name in x if not is_numeric_dtype(x[name])]
        self._forest.fit(self._matrix(x, fit=True), y)
        self.classes = tuple(sorted(str(label) for label in y.unique()))

    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Unknown categories remain missing rather than changing the feature mapping."""
        return np.asarray(self._forest.predict_proba(self._matrix(x)), dtype=np.float64)
