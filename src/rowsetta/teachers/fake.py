import os
from time import sleep

import numpy as np
import pandas as pd
from numpy.typing import NDArray

MILLISECONDS_PER_SECOND = 1_000


class FakeTeacher:
    """Deterministic nearest-centroid teacher for tests, never product inference."""

    def __init__(self) -> None:
        self.classes: tuple[str, ...] = ()
        self._columns: tuple[str, ...] = ()
        self._categories: dict[str, tuple[str, ...]] = {}
        self._centroids: NDArray[np.float64] = np.empty((0, 0))
        self._scale: NDArray[np.float64] = np.empty(0)
        self._fill: NDArray[np.float64] = np.empty(0)
        self._delay_ms = float(os.environ.get("ROWSETTA_FAKE_DELAY_MS", "0"))
        if not np.isfinite(self._delay_ms) or self._delay_ms < 0:
            message = "ROWSETTA_FAKE_DELAY_MS must be a finite nonnegative number."
            raise ValueError(message)

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        """Learn per-class centroids with training-only encodings and scaling."""
        self.classes = tuple(sorted(str(label) for label in y.unique()))
        self._columns = tuple(x.columns)
        self._categories = {
            name: tuple(sorted(str(value) for value in x[name].dropna().unique()))
            for name in self._columns
            if not pd.api.types.is_numeric_dtype(x[name].dtype)
        }
        values = self._encode(x)
        counts = np.isfinite(values).sum(axis=0)
        self._fill = np.nansum(values, axis=0) / np.maximum(counts, 1)
        values = np.where(np.isnan(values), self._fill, values)
        self._scale = np.std(values, axis=0)
        self._scale[self._scale == 0] = 1
        values = values / self._scale
        self._centroids = np.stack(
            [values[y.to_numpy() == label].mean(axis=0) for label in self.classes]
        )

    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Convert distances to normalized class probabilities, optionally delayed."""
        if not self.classes:
            message = "Fit the teacher before predicting probabilities."
            raise ValueError(message)
        if self._delay_ms:
            sleep(self._delay_ms / MILLISECONDS_PER_SECOND)
        values = self._encode(x)
        values = np.where(np.isnan(values), self._fill, values) / self._scale
        distances = np.square(values[:, None, :] - self._centroids).sum(axis=2)
        logits = -distances
        weights = np.exp(logits - logits.max(axis=1, keepdims=True))
        return weights / weights.sum(axis=1, keepdims=True)

    def _encode(self, frame: pd.DataFrame) -> NDArray[np.float64]:
        columns: list[NDArray[np.float64]] = []
        for name in self._columns:
            series = frame[name]
            if name in self._categories:
                mapping = {value: index for index, value in enumerate(self._categories[name])}
                series = series.map(mapping)
            columns.append(np.asarray(series.to_numpy(na_value=np.nan), dtype=np.float64))
        return np.column_stack(columns)
