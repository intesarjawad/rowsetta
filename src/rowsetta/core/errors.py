import shlex
from decimal import Decimal

BYTES_PER_MB = 1_000_000


class UserError(Exception):
    """An expected failure with an explanation and a concrete recovery step."""

    what: str
    next_step: str

    def __init__(self, what: str, next_step: str) -> None:
        self.what = what
        self.next_step = next_step
        super().__init__(what)


class FileTooLargeError(UserError):
    """The input exceeds the caller's byte budget before any parsing occurs."""

    def __init__(self, size_bytes: int, max_bytes: int, *, file_name: str = "data.csv") -> None:
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        self.file_name = file_name
        size_mb = Decimal(size_bytes) / BYTES_PER_MB
        limit_mb = Decimal(max_bytes) / BYTES_PER_MB
        super().__init__(
            f"`{file_name}` is {size_mb:f} MB; the limit is {limit_mb:f} MB "
            "(50 MB in the browser).",
            shlex.join(
                [
                    "rowsetta",
                    "open",
                    file_name,
                    "--max-file-mb",
                    str((size_bytes + BYTES_PER_MB - 1) // BYTES_PER_MB),
                ]
            ),
        )


class TooManyColumnsError(UserError):
    """The input needs an explicit column selection to fit the model."""

    def __init__(
        self, column_names: tuple[str, ...], max_columns: int, *, file_name: str = "data.csv"
    ) -> None:
        self.column_names = column_names
        self.max_columns = max_columns
        self.file_name = file_name
        super().__init__(
            f"`{file_name}` has {len(column_names)} columns; "
            f"the model takes at most {max_columns}.",
            shlex.join(
                [
                    "rowsetta",
                    "open",
                    file_name,
                    "--columns",
                    ",".join(column_names[:max_columns]),
                ]
            ),
        )


class UnknownColumnsError(UserError):
    """A column selection names columns the file does not have."""

    def __init__(
        self,
        unknown: tuple[str, ...],
        column_names: tuple[str, ...],
        max_columns: int,
        *,
        file_name: str = "data.csv",
    ) -> None:
        self.unknown = unknown
        self.column_names = column_names
        self.max_columns = max_columns
        self.file_name = file_name
        super().__init__(
            f"`{file_name}` has no column named {', '.join(f'`{name}`' for name in unknown)}.",
            shlex.join(
                [
                    "rowsetta",
                    "open",
                    file_name,
                    "--columns",
                    ",".join(column_names[:max_columns]),
                ]
            ),
        )


class BadCsvError(UserError):
    """The input could not be decoded or parsed as supported CSV."""

    def __init__(self, reason: str, line_number: int, *, file_name: str = "data.csv") -> None:
        self.reason = reason
        self.line_number = line_number
        self.file_name = file_name
        if reason == "Invalid UTF-8 encoding":
            next_step = (
                f"{shlex.join(['iconv', '-f', 'WINDOWS-1252', '-t', 'UTF-8', file_name])} "
                f"> {shlex.quote(file_name + '.utf8.csv')} && "
                f"{shlex.join(['rowsetta', 'open', file_name + '.utf8.csv'])}"
            )
        else:
            repair = (
                "Add at least one data row beneath the header"
                if reason == "A CSV needs a header and at least one data row"
                else f"Fix the fields or quoting near line {line_number}"
            )
            next_step = (
                f"{repair}, re-export as CSV, then run "
                f"{shlex.join(['rowsetta', 'open', file_name])}."
            )
        super().__init__(
            f"Could not read `{file_name}`: {reason} (line {line_number}).",
            next_step,
        )


class NotServedError(UserError):
    """An evaluation edit did not address the currently served random row."""

    def __init__(self) -> None:
        super().__init__(
            "Evaluation rows are served at random.",
            "Press e and label the row shown",
        )


NotServed = NotServedError


class WorkspaceError(UserError):
    """The requested operation is unavailable for the current workspace inputs."""

    def __init__(
        self,
        what: str,
        next_step: str = "rowsetta demo; load a CSV and choose its target.",
        *,
        status_code: int = 409,
    ) -> None:
        self.status_code = status_code
        super().__init__(what, next_step)


class NeedLabelsError(UserError):
    """Each configured class needs enough human examples for the teacher."""

    def __init__(self, missing: dict[str, int]) -> None:
        self.missing = missing
        needed = "; ".join(
            f"{count} more {'row' if count == 1 else 'rows'} of: {label}"
            for label, count in missing.items()
        )
        super().__init__(
            "Proposals start once every class has 2 labels.",
            f"rowsetta demo; label {needed}",
        )
