from rowsetta.core.audit import NeedAuditLabelsError
from rowsetta.core.errors import (
    BadCsvError,
    FileTooLargeError,
    NeedLabelsError,
    TooManyColumnsError,
    UserError,
    WorkspaceError,
)


class ApiError(UserError):
    """An HTTP boundary failure with a public recovery step."""

    def __init__(
        self,
        what: str,
        next_step: str = "rowsetta demo; reopen the local app and retry.",
        *,
        status_code: int = 400,
    ) -> None:
        self.status_code = status_code
        super().__init__(what, next_step)


class FrontendMissingError(ApiError):
    """An editable install can serve the API before the frontend is built."""

    def __init__(self) -> None:
        super().__init__(
            "frontend not built; run make setup",
            "make setup",
            status_code=503,
        )


class ModelUnavailableError(ApiError):
    """Local model setup failed without falling back to a network download."""

    def __init__(self) -> None:
        super().__init__(
            "The model file is missing or failed its checksum.",
            "rowsetta doctor --fix",
            status_code=503,
        )


def error_body(error: UserError) -> dict[str, object]:
    """Keep the same recovery fields across middleware, routes and refit failures."""
    body: dict[str, object] = {"error": error.what, "next_step": error.next_step}
    if isinstance(error, (NeedLabelsError, NeedAuditLabelsError)):
        body["missing"] = error.missing
    return body


def error_status(error: UserError) -> int:
    """Translate domain failures only at the HTTP boundary."""
    if isinstance(error, (ApiError, WorkspaceError)):
        return error.status_code
    if isinstance(error, (FileTooLargeError, TooManyColumnsError)):
        return 413
    if isinstance(error, BadCsvError):
        return 400
    return 409
