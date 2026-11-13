import importlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd
from pandas.api.types import is_integer_dtype

from rowsetta.core.features import TEXT_DISTINCT_RATIO, teacher_frame
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray

MIN_HUMAN_LABELS = 30
MIN_CLASSES = 2
CV_FOLDS = 5
IDENTIFIER_DISTINCT_RATIO = 0.95
SINGLE_COLUMN_MIN_SCORE = 0.95
NAME_HINT = re.compile(r"(^|_)(id|uuid|label|target|outcome|result|class|y)($|_)", re.IGNORECASE)


@dataclass(frozen=True)
class LeakHint:
    """A column warning with a balanced-accuracy score for single-column checks."""

    column: str
    kind: Literal["identifier", "single-column", "name"]
    reason: str
    score: float | None


def find_leaks(table: Table, store: LabelStore) -> list[LeakHint]:
    """Find identifiers, near-perfect predictors and suspicious names using human labels."""
    labels = store.training_rows()
    if len(labels) < MIN_HUMAN_LABELS or len(set(labels.values())) < MIN_CLASSES:
        return []
    columns = [
        column
        for column in table.columns
        if column.name not in store.excluded_columns and column.name != store.target
    ]
    dropped = {
        column.name
        for column in columns
        if column.kind == "text" and column.distinct_ratio > TEXT_DISTINCT_RATIO
    }
    prepared = (
        teacher_frame(table, store).frame
        if any(column.name not in dropped for column in columns)
        else None
    )
    hints: list[LeakHint] = []
    for column in columns:
        series = table.frame[column.name]
        increasing_integer = (
            is_integer_dtype(series.dtype)
            and len(series) > 1
            and series.notna().all()
            and series.is_monotonic_increasing
            and series.is_unique
        )
        if column.name not in dropped and (
            (column.kind != "numeric" and column.distinct_ratio > IDENTIFIER_DISTINCT_RATIO)
            or increasing_integer
        ):
            hints.append(
                LeakHint(
                    column.name,
                    "identifier",
                    f"`{column.name}` is unique for nearly every row; "
                    "the model can only memorise it.",
                    None,
                )
            )
        if prepared is not None and column.name in prepared:
            score = _stump_score(prepared[[column.name]], pd.Series(labels))
            if score >= SINGLE_COLUMN_MIN_SCORE:
                hints.append(
                    LeakHint(
                        column.name,
                        "single-column",
                        f"`{column.name}` alone predicts the label {score:.0%} of the time "
                        "(balanced). If it is recorded after the outcome, it is a leak.",
                        score,
                    )
                )
        if NAME_HINT.search(column.name):
            hints.append(
                LeakHint(
                    column.name,
                    "name",
                    f"The name of `{column.name}` suggests an identifier or an outcome.",
                    None,
                )
            )
    return hints


def _stump_score(frame: pd.DataFrame, labels: pd.Series) -> float:
    features = frame.loc[labels.index]
    stump = importlib.import_module("sklearn.tree").DecisionTreeClassifier(
        max_depth=1, random_state=7
    )
    pipeline = importlib.import_module("sklearn.pipeline")
    preprocessing = importlib.import_module("sklearn.preprocessing")
    cross_val_score: Callable[..., NDArray[np.float64]] = importlib.import_module(
        "sklearn.model_selection"
    ).cross_val_score
    if not pd.api.types.is_numeric_dtype(features.iloc[:, 0].dtype):
        features = features.astype(object).where(features.notna(), np.nan)
        estimator = pipeline.make_pipeline(
            preprocessing.OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
            stump,
        )
    else:
        estimator = pipeline.make_pipeline(stump)
    return float(
        cross_val_score(
            estimator,
            features,
            labels,
            cv=CV_FOLDS,
            scoring="balanced_accuracy",
            error_score="raise",
        ).mean()
    )
