import csv
import io
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rowsetta.core.errors import (
    BadCsvError,
    FileTooLargeError,
    TooManyColumnsError,
    UnknownColumnsError,
)
from rowsetta.core.table import MAX_COLS, MAX_FILE_BYTES, MAX_ROWS, SAMPLE_SEED, load_csv

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DATASETS = Path(__file__).resolve().parents[2] / "src" / "rowsetta" / "datasets"


@pytest.mark.parametrize(
    ("name", "numeric", "categorical"),
    [
        (
            "penguins",
            "bill_length_mm bill_depth_mm flipper_length_mm body_mass_g year",
            "species island sex",
        ),
        (
            "bank",
            "age balance day duration campaign pdays previous",
            "job marital education default housing loan contact month poutcome y",
        ),
        (
            "adult",
            "age fnlwgt education-num capital-gain capital-loss hours-per-week",
            (
                "workclass education marital-status occupation relationship race sex "
                "native-country income"
            ),
        ),
    ],
)
def test_demo_kinds_and_subsecond_loading(
    name: str, numeric: str, categorical: str, record_property: Callable[[str, object], None]
) -> None:
    start = perf_counter()
    table = load_csv((DATASETS / f"{name}.csv").read_bytes())
    elapsed = perf_counter() - start
    record_property("load_seconds", elapsed)

    assert elapsed < 1
    expected = dict.fromkeys(numeric.split(), "numeric") | dict.fromkeys(
        categorical.split(), "categorical"
    )
    assert {column.name: column.kind for column in table.columns} == expected


@pytest.mark.parametrize("separator", [",", ";", "\t"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_supported_separators_and_bom(separator: str, encoding: str) -> None:
    data = f'id{separator}name\n1{separator}"a,b; c\td"\n2{separator}سلام\n'

    table = load_csv(data.encode(encoding))

    assert table.frame.to_dict("list") == {"id": [1, 2], "name": ["a,b; c\td", "سلام"]}
    assert table.source_rows == 2
    assert [info.kind for info in table.columns] == ["numeric", "categorical"]


def test_sampling_preserves_original_row_ids_and_source_count() -> None:
    frame = pd.DataFrame({"id": range(MAX_ROWS + 1), "value": range(MAX_ROWS + 1)})
    data = frame.to_csv(index=False).encode()

    first = load_csv(data)
    second = load_csv(data)
    expected = frame.sample(n=MAX_ROWS, random_state=SAMPLE_SEED).sort_index()

    assert first.source_rows == MAX_ROWS + 1
    assert len(first.frame) == MAX_ROWS
    pd.testing.assert_frame_equal(first.frame, expected)
    pd.testing.assert_frame_equal(first.frame, second.frame)


def test_browser_limits_and_inference_use_only_kept_rows() -> None:
    frame = pd.DataFrame({"description": [f"entry {index}" for index in range(200)]})

    table = load_csv(frame.to_csv(index=False).encode(), max_rows=20, max_bytes=50_000_000)

    assert table.source_rows == 200
    assert len(table.frame) == 20
    assert table.columns[0].kind == "categorical"
    assert table.frame.index.is_monotonic_increasing


def test_at_row_cap_does_not_sample() -> None:
    table = load_csv(b"value\n1\n2\n", max_rows=2)

    assert list(table.frame.index) == [0, 1]
    assert table.source_rows == 2


def test_file_limit_is_checked_before_decoding_or_parsing() -> None:
    with pytest.raises(FileTooLargeError) as caught:
        load_csv(b"\xff" * 5, max_bytes=4)

    assert caught.value.size_bytes == 5
    assert caught.value.max_bytes == 4
    assert caught.value.next_step == "rowsetta open data.csv --max-file-mb 1"


def test_file_at_byte_limit_loads() -> None:
    data = b"a,b\n1,2\n"

    assert load_csv(data, max_bytes=len(data)).frame.shape == (1, 2)
    assert MAX_FILE_BYTES == 200_000_000


def test_column_limit_has_an_executable_next_step() -> None:
    names = tuple(f"column_{index}" for index in range(MAX_COLS + 1))
    data = (",".join(names) + "\n").encode()

    with pytest.raises(TooManyColumnsError) as caught:
        load_csv(data)

    assert caught.value.column_names == names
    assert caught.value.what == "`data.csv` has 101 columns; the model takes at most 100."
    assert caught.value.next_step == (
        "rowsetta open data.csv --columns " + ",".join(names[:MAX_COLS])
    )


def test_selected_columns_fit_a_wide_file_in_the_requested_order() -> None:
    names = tuple(f"column_{index}" for index in range(MAX_COLS + 1))
    data = (",".join(names) + "\n" + ",".join("1" for _ in names) + "\n").encode()

    table = load_csv(data, keep_columns=("column_100", "column_0", "column_100"))

    assert list(table.frame.columns) == ["column_100", "column_0"]
    assert [column.name for column in table.columns] == ["column_100", "column_0"]


def test_unknown_selected_columns_name_each_missing_column() -> None:
    with pytest.raises(UnknownColumnsError) as caught:
        load_csv(b"species,island\nAdelie,Dream\n", keep_columns=("species", "isle", "beak"))

    assert caught.value.unknown == ("isle", "beak")
    assert caught.value.what == "`data.csv` has no column named `isle`, `beak`."
    assert caught.value.next_step == "rowsetta open data.csv --columns species,island"


def test_boolean_columns_become_lowercase_categorical_strings() -> None:
    table = load_csv(b"id,flag,nullable\n1,True,true\n2,False,\n3,TRUE,false\n")

    assert table.frame["flag"].tolist() == ["true", "false", "true"]
    assert table.frame["nullable"].dropna().tolist() == ["true", "false"]
    assert [info.kind for info in table.columns] == ["numeric", "categorical", "categorical"]
    assert table.columns[2].missing_ratio == pytest.approx(1 / 3)
    assert table.columns[2].distinct_ratio == pytest.approx(2 / 3)


@pytest.mark.parametrize(("valid_dates", "expected_kind"), [(94, "text"), (95, "datetime")])
def test_datetime_threshold_and_precedence(valid_dates: int, expected_kind: str) -> None:
    dates = pd.date_range("2024-01-01", periods=valid_dates).strftime("%Y-%m-%d").tolist()
    invalid = [f"invalid {index}" for index in range(100 - valid_dates)]
    frame = pd.DataFrame({"date": [*dates, *invalid, None]})

    table = load_csv(frame.to_csv(index=False).encode())

    assert table.columns[0].kind == expected_kind
    assert table.columns[0].distinct_ratio == pytest.approx(100 / 101)
    assert table.columns[0].missing_ratio == pytest.approx(1 / 101)
    assert isinstance(table.frame.loc[0, "date"], str)


@pytest.mark.parametrize(("rows", "expected_kind"), [(1020, "text"), (1021, "categorical")])
def test_distinct_ratio_threshold(rows: int, expected_kind: str) -> None:
    frame = pd.DataFrame({"category": [f"value {index % 51}" for index in range(rows)]})

    assert load_csv(frame.to_csv(index=False).encode()).columns[0].kind == expected_kind


def test_fifty_distinct_values_are_categorical_even_when_they_are_dates() -> None:
    frame = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=50).astype(str)})

    assert load_csv(frame.to_csv(index=False).encode()).columns[0].kind == "categorical"


def test_header_only_and_single_column_files() -> None:
    with pytest.raises(BadCsvError, match="at least one data row"):
        load_csv(b"a,b\n")
    single = load_csv(b'value\n"a,b"\n"c;d"\n')

    assert single.frame["value"].tolist() == ["a,b", "c;d"]


def test_sniff_window_can_end_inside_a_utf8_character() -> None:
    data = ('id,text\n1,"' + "x" * (65_536 - 12) + '🙂"\n').encode()

    assert load_csv(data).frame.shape == (1, 2)


@pytest.mark.parametrize(
    "data",
    [b"", b"\xef\xbb\xbf", b"a,b\n1,\xff\n", b'a,b\n1,"unfinished\n', b"a,b\n1,2\n3,4,5\n"],
)
def test_bad_csv_has_reason_and_line_number(data: bytes) -> None:
    with pytest.raises(BadCsvError) as caught:
        load_csv(data)

    assert "Could not read `data.csv`:" in caught.value.what
    assert "line " in caught.value.what
    assert caught.value.reason
    assert caught.value.line_number >= 1


def test_worst_case_fixture() -> None:
    data = (FIXTURES / "worst_case.csv").read_bytes()
    table = load_csv(data)
    with io.StringIO(data.decode()) as stream:
        source = list(csv.reader(stream))

    assert table.frame.shape == (3, MAX_COLS)
    assert all(len(name) == 120 for name in table.frame.columns)
    assert table.frame.iloc[:, -1].isna().all()
    assert table.columns[-1].missing_ratio == 1
    assert table.frame.iloc[0, 0] == source[1][0]
    assert '"' in source[1][0]
    assert "🙂" in source[1][0]
    assert "مرحبا" in source[1][0]


csv_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    max_size=30,
)
csv_cell = st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), csv_text)


@st.composite
def mixed_frames(draw: st.DrawFn) -> pd.DataFrame:
    rows = draw(st.lists(st.tuples(csv_cell, csv_text), max_size=20))
    return pd.DataFrame(rows, columns=["mixed", "text"], dtype=object)


@pytest.mark.native
@settings(derandomize=True)
@given(frame=mixed_frames())
def test_mixed_dataframe_csv_round_trip_preserves_shape(frame: pd.DataFrame) -> None:
    if frame.empty:
        with pytest.raises(BadCsvError, match="at least one data row"):
            load_csv(frame.to_csv(index=False).encode())
        return
    table = load_csv(frame.to_csv(index=False).encode())

    assert table.frame.shape == frame.shape
    assert list(table.frame.columns) == list(frame.columns)
