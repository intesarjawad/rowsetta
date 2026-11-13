import importlib
import importlib.util
import inspect
import pkgutil
import shlex

import pytest

from rowsetta.api.errors import ApiError, FrontendMissingError, ModelUnavailableError
from rowsetta.core.audit import NeedAuditLabelsError
from rowsetta.core.errors import (
    BadCsvError,
    FileTooLargeError,
    NeedLabelsError,
    NotServed,
    TooManyColumnsError,
    UnknownColumnsError,
    UserError,
    WorkspaceError,
)
from rowsetta.core.export.sql import UnsupportedDatetimeSplitError

ERROR_EXAMPLES: tuple[UserError, ...] = (
    FileTooLargeError(200_000_001, 200_000_000),
    TooManyColumnsError(tuple(f"column_{index}" for index in range(101)), 100),
    UnknownColumnsError(("isle",), ("species", "island"), 100),
    BadCsvError("Unexpected end of quoted field", 3),
    NotServed(),
    NeedLabelsError({"Chinstrap": 1}),
    NeedAuditLabelsError({"Chinstrap": 2}),
    WorkspaceError("No CSV is loaded."),
    ApiError("A valid launch session is required.", status_code=403),
    FrontendMissingError(),
    ModelUnavailableError(),
    UnsupportedDatetimeSplitError("created_at"),
)


def _discover_user_errors() -> set[type[UserError]]:
    error_types: set[type[UserError]] = set()
    for package_name in ("rowsetta.core", "rowsetta.api"):
        if importlib.util.find_spec(package_name) is None:
            continue
        package = importlib.import_module(package_name)
        for module_info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            module = importlib.import_module(module_info.name)
            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if issubclass(candidate, UserError) and candidate is not UserError:
                    error_types.add(candidate)
    return error_types


@pytest.mark.native
def test_every_user_error_has_a_contract_example() -> None:
    assert _discover_user_errors() == {type(error) for error in ERROR_EXAMPLES}


@pytest.mark.parametrize("error", ERROR_EXAMPLES, ids=lambda error: type(error).__name__)
def test_error_contract_fields_are_nonempty(error: UserError) -> None:
    assert error.what.strip()
    assert error.next_step.strip()
    assert str(error) == error.what


@pytest.mark.parametrize("error", ERROR_EXAMPLES, ids=lambda error: type(error).__name__)
def test_cli_recovery_starts_with_a_named_command(error: UserError) -> None:
    if isinstance(error, NotServed):
        assert error.next_step == "Press e and label the row shown"
        return
    if isinstance(error, BadCsvError):
        assert "re-export" in error.next_step
        return
    assert error.next_step.startswith(("rowsetta ", "uvx ", "make ", "iconv "))


def test_file_limit_message_preserves_bytes_and_rounds_up_recovery_budget() -> None:
    error = FileTooLargeError(200_000_001, 200_000_000)

    assert error.what == (
        "`data.csv` is 200.000001 MB; the limit is 200 MB (50 MB in the browser)."
    )
    assert error.next_step == "rowsetta open data.csv --max-file-mb 201"


def test_recovery_commands_quote_user_supplied_arguments() -> None:
    file_name = "sales $(date).csv"
    columns = ("customer name", 'a"b', "cost; currency")
    size_error = FileTooLargeError(2, 1, file_name=file_name)
    column_error = TooManyColumnsError(columns, 2, file_name=file_name)

    assert shlex.split(size_error.next_step) == [
        "rowsetta",
        "open",
        file_name,
        "--max-file-mb",
        "1",
    ]
    assert shlex.split(column_error.next_step) == [
        "rowsetta",
        "open",
        file_name,
        "--columns",
        'customer name,a"b',
    ]


def test_bad_csv_recovery_opens_the_converted_file() -> None:
    file_name = "sales $(date).csv"
    error = BadCsvError("Invalid UTF-8 encoding", 2, file_name=file_name)
    command, reopen = error.next_step.split(" && ", maxsplit=1)
    assert shlex.split(command) == [
        "iconv",
        "-f",
        "WINDOWS-1252",
        "-t",
        "UTF-8",
        file_name,
        ">",
        file_name + ".utf8.csv",
    ]
    assert shlex.split(reopen) == ["rowsetta", "open", file_name + ".utf8.csv"]


@pytest.mark.parametrize(
    ("reason", "advice"),
    [
        ("A CSV needs a header and at least one data row", "Add at least one data row"),
        ("Data rows have more fields than the header", "Fix the fields or quoting"),
    ],
)
def test_non_encoding_csv_errors_offer_data_repairs(reason: str, advice: str) -> None:
    error = BadCsvError(reason, 1)
    assert advice in error.next_step
    assert "rowsetta open data.csv" in error.next_step
    assert "iconv" not in error.next_step
