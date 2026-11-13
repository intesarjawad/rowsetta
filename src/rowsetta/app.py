import os

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from rowsetta.api.errors import (
    ApiError,
    FrontendMissingError,
    ModelUnavailableError,
    error_body,
    error_status,
)
from rowsetta.api.routes import workspace_router
from rowsetta.api.runtime import WorkspaceRuntime
from rowsetta.api.schemas import Health
from rowsetta.api.security import (
    ALLOWED_HOSTS,
    ErrorContractMiddleware,
    SessionMiddleware,
    SessionSecurity,
)
from rowsetta.core.errors import UserError
from rowsetta.core.table import MAX_FILE_BYTES, MAX_ROWS
from rowsetta.core.teacher import Teacher
from rowsetta.core.workspace import Workspace
from rowsetta.storage import SessionStorage
from rowsetta.teachers.fake import FakeTeacher
from rowsetta.teachers.tabicl import TabICLTeacher


@dataclass(frozen=True)
class LaunchCsv:
    """A CSV loaded before the app starts, so its errors reach the command line.

    A user's own file keeps its session beside it; a bundled file keeps it in the data dir.
    """

    path: Path
    session_beside: bool
    max_bytes: int = MAX_FILE_BYTES
    columns: tuple[str, ...] | None = None


def create_app(
    *,
    teacher: Teacher,
    security: SessionSecurity,
    static_dir: Path | None = None,
    data_dir: Path | None = None,
    csv: LaunchCsv | None = None,
) -> FastAPI:
    """Build an isolated local app whose teacher and session belong to one launch."""
    max_rows = row_limit()
    workspace = _workspace(data_dir, csv, max_rows=max_rows)
    runtime = WorkspaceRuntime(workspace, teacher)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # A resumed session already has labels, so its proposals start without an edit.
        runtime.schedule()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, security=security)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.add_middleware(ErrorContractMiddleware)

    @app.exception_handler(UserError)
    async def user_error(_request: Request, error: UserError) -> JSONResponse:
        return JSONResponse(error_body(error), status_code=error_status(error))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        error = ApiError("The request fields are invalid.", status_code=422)
        return JSONResponse(error_body(error), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        if (
            isinstance(error.detail, dict)
            and "error" in error.detail
            and "next_step" in error.detail
        ):
            return JSONResponse(error.detail, status_code=error.status_code)
        failure = ApiError(str(error.detail), status_code=error.status_code)
        return JSONResponse(error_body(failure), status_code=error.status_code)

    @app.get("/health")
    async def health() -> Health:
        return Health(ok=True)

    static = static_dir if static_dir is not None else Path(__file__).parent / "static"

    @app.get("/")
    async def index() -> Response:
        if not (static / "index.html").is_file():
            raise FrontendMissingError
        return FileResponse(static / "index.html")

    app.include_router(
        workspace_router(
            runtime,
            max_rows=max_rows,
            dev_states=os.environ.get("ROWSETTA_STATES") == "1",
        )
    )
    if (static / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static, html=True))
    return app


def _workspace(data_dir: Path | None, csv: LaunchCsv | None, *, max_rows: int) -> Workspace:
    if csv is None:
        return Workspace(SessionStorage(data_dir=data_dir))
    source_path = csv.path if csv.session_beside else None
    workspace = Workspace(
        SessionStorage(data_dir=data_dir, source_path=source_path), max_bytes=csv.max_bytes
    )
    workspace.load(
        csv.path.read_bytes(),
        csv.path.name,
        max_rows=max_rows,
        columns=csv.columns,
        display_name=str(csv.path),
    )
    return workspace


def row_limit() -> int:
    """Read the working-sample cap; saved sessions only resume under the same cap."""
    return int(os.environ.get("ROWSETTA_MAX_ROWS", str(MAX_ROWS)))


def local_teacher() -> Teacher:
    """Choose explicit test inference or verified local weights without egress."""
    if os.environ.get("ROWSETTA_TEACHER") == "fake":
        return FakeTeacher()
    try:
        return TabICLTeacher()
    except (OSError, RuntimeError, SystemExit) as error:
        raise ModelUnavailableError from error
