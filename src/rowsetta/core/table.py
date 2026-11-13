import codecs
import csv
import io
import re
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pandas.api.types import infer_dtype, is_bool_dtype, is_numeric_dtype

from rowsetta.core.errors import (
    BadCsvError,
    FileTooLargeError,
    TooManyColumnsError,
    UnknownColumnsError,
)

MAX_ROWS = 10_000
MAX_COLS = 100  # TabICLv2 is pretrained on at most 100 columns.
MAX_FILE_BYTES = 200_000_000
SAMPLE_SEED = 7
SNIFF_BYTES = 65_536
MAX_CATEGORICAL_VALUES = 50
CATEGORICAL_DISTINCT_RATIO = 0.05
DATETIME_PARSE_RATIO = 0.95


@dataclass(frozen=True)
class ColumnInfo:
    """Inferred kind and ratios measured over the kept rows, including missing rows."""

    name: str
    kind: Literal["numeric", "categorical", "text", "datetime"]
    distinct_ratio: float
    missing_ratio: float


@dataclass(frozen=True)
class Table:
    """Working data whose index preserves original zero-based source row ids.

    The record is frozen; callers must treat its mutable frame as read-only.
    """

    frame: pd.DataFrame
    columns: tuple[ColumnInfo, ...]
    source_rows: int


def load_csv(
    data: bytes,
    *,
    max_rows: int = MAX_ROWS,
    max_bytes: int = MAX_FILE_BYTES,
    keep_columns: tuple[str, ...] | None = None,
) -> Table:
    """Decode UTF-8 CSV, enforce limits, then sample before inferring column kinds.

    Raises FileTooLargeError, TooManyColumnsError, UnknownColumnsError or BadCsvError for
    rejected input. Browser callers supply their own row and byte budgets; no filesystem
    access occurs. `keep_columns` keeps only those columns, in the order given.
    """
    if len(data) > max_bytes:
        raise FileTooLargeError(len(data), max_bytes)
    if max_rows <= 0:
        message = "max_rows must be positive."
        raise ValueError(message)
    frame = _read_csv(data)
    if keep_columns is not None:
        unknown = tuple(name for name in keep_columns if name not in frame.columns)
        if unknown:
            raise UnknownColumnsError(unknown, tuple(frame.columns), MAX_COLS)
        frame = frame.loc[:, list(dict.fromkeys(keep_columns))]
    if len(frame.columns) > MAX_COLS:
        raise TooManyColumnsError(tuple(frame.columns), MAX_COLS)
    if frame.empty:
        reason = "A CSV needs a header and at least one data row"
        raise BadCsvError(reason, 1)
    # pandas otherwise interprets surplus fields on the first data row as an index.
    if not isinstance(frame.index, pd.RangeIndex):
        reason = "Data rows have more fields than the header"
        raise BadCsvError(reason, 2)
    source_rows = len(frame)
    if source_rows > max_rows:
        frame = frame.sample(n=max_rows, random_state=SAMPLE_SEED).sort_index()
    columns = tuple(_infer_column(frame, name) for name in frame.columns)
    return Table(frame=frame, columns=columns, source_rows=source_rows)


def _read_csv(data: bytes) -> pd.DataFrame:
    try:
        separator = _sniff_separator(data)
        frame = pd.read_csv(io.BytesIO(data), sep=separator, encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        line_number = error.object[: error.start].count(b"\n") + 1
        reason = "Invalid UTF-8 encoding"
        raise BadCsvError(reason, line_number) from error
    except pd.errors.EmptyDataError as error:
        reason = "A CSV needs a header and at least one data row"
        raise BadCsvError(reason, 1) from error
    except pd.errors.ParserError as error:
        reason = str(error).strip()
        raise BadCsvError(reason, _parser_line_number(reason)) from error

    return frame


def _sniff_separator(data: bytes) -> str:
    # final=False permits a UTF-8 code point to straddle the sniff window boundary.
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    sample = decoder.decode(data[:SNIFF_BYTES], final=False)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        # A truncated record or malformed later row must not obscure a valid header.
        header = sample.split("\n", maxsplit=1)[0]
        try:
            return csv.Sniffer().sniff(header, delimiters=",;\t").delimiter
        except csv.Error:
            # A single-column CSV has no separator to sniff.
            return ","


def _parser_line_number(reason: str) -> int:
    line = re.search(r"line (\d+)", reason)
    if line:
        return int(line[1])
    row = re.search(r"starting at row (\d+)", reason)
    return int(row[1]) + 1 if row else 1


def _infer_column(frame: pd.DataFrame, name: str) -> ColumnInfo:
    series = frame[name]
    if is_bool_dtype(series.dtype) or infer_dtype(series, skipna=True) == "boolean":
        series = series.map({True: "true", False: "false"})
        frame[name] = series
    distinct = series.nunique()
    distinct_ratio = distinct / len(series) if len(series) else 0.0
    missing_ratio = float(series.isna().mean()) if len(series) else 0.0
    if is_numeric_dtype(series.dtype):
        kind = "numeric"
    elif distinct <= MAX_CATEGORICAL_VALUES or distinct_ratio < CATEGORICAL_DISTINCT_RATIO:
        kind = "categorical"
    else:
        non_null = series.dropna()
        parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
        kind = "datetime" if parsed.notna().mean() >= DATETIME_PARSE_RATIO else "text"
    return ColumnInfo(name, kind, distinct_ratio, missing_ratio)
