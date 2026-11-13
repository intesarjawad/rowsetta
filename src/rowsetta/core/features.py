from dataclasses import dataclass

import pandas as pd

from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table

EPOCH_DAYS = pd.Timestamp("1970-01-01", tz="UTC")
DAY = pd.Timedelta(days=1)
TEXT_DISTINCT_RATIO = 0.5


@dataclass(frozen=True)
class TeacherFrame:
    """Model features in source row order, with skipped free-text columns listed."""

    frame: pd.DataFrame
    dropped_columns: tuple[str, ...]


def teacher_frame(table: Table, store: LabelStore) -> TeacherFrame:
    """Remove target and excluded columns, preserving categoricals and missing cells."""
    excluded = store.excluded_columns | {store.target}
    dropped = tuple(
        column.name
        for column in table.columns
        if column.name not in excluded
        and column.kind == "text"
        and column.distinct_ratio > TEXT_DISTINCT_RATIO
    )
    frame = table.frame.drop(columns=list(excluded | set(dropped)), errors="ignore").copy()
    for column in table.columns:
        if column.name in frame and column.kind == "datetime":
            dates = pd.to_datetime(frame[column.name], errors="coerce", format="mixed", utc=True)
            # TabICL accepts numerics and categoricals, so dates use fractional epoch days.
            frame[column.name] = (dates - EPOCH_DAYS) / DAY
    if frame.shape[1] == 0:
        message = "No usable features remain. Include a numeric or categorical column."
        raise ValueError(message)
    return TeacherFrame(frame, dropped)
