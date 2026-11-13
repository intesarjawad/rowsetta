"""SQL export route for a shell-supplied snapshot of the current rule."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import TypeAdapter

from rowsetta.api.errors import ApiError
from rowsetta.api.presentation import event_stream, export_metadata, workspace_state
from rowsetta.api.runtime import WorkspaceRuntime
from rowsetta.api.schemas import (
    Audit,
    Cell,
    ColumnInfo,
    Distilled,
    DistillInput,
    EvalNext,
    ExclusionInput,
    LabelInput,
    LeafLine,
    LeakHint,
    Suspect,
    Suspects,
    TablePage,
    TargetInput,
    ThresholdInput,
    WorkspaceState,
)
from rowsetta.api.sql_check import sql_check, sql_check_data
from rowsetta.api.upload import table_upload
from rowsetta.core.distill import Student, disagreements, leaf_summary
from rowsetta.core.errors import UserError, WorkspaceError
from rowsetta.core.export.dbt import to_dbt, validate_names
from rowsetta.core.export.json import to_json
from rowsetta.core.export.python import to_python
from rowsetta.core.export.sql import Certificate, Dialect, NotExecuted, to_sql
from rowsetta.core.leaks import find_leaks
from rowsetta.core.workspace import Workspace

type ExportFormat = Literal["sql", "dbt", "python", "json"]
EXPORT_MEDIA_TYPES: dict[ExportFormat, str] = {
    "sql": "application/sql",
    "python": "text/x-python",
    "json": "application/json",
}


@dataclass(frozen=True)
class SqlExportContext:
    """The source file and immutable rule facts selected by the shell."""

    source: Path
    student: Student
    certificate: Certificate


def sql_export_router(current_export: Callable[[], SqlExportContext]) -> APIRouter:
    """Build the export route without owning workspace state or authentication."""
    router = APIRouter()

    @router.get("/export")
    def export_sql(
        _export_format: Annotated[Literal["sql"], Query(alias="format")] = "sql",
        dialect: Dialect = "duckdb",
    ) -> Response:
        context = current_export()
        facts = replace(context.certificate, execution=NotExecuted("verification pending"))
        try:
            checked_sql = to_sql(context.student, dialect="duckdb", certificate=facts)
            headerless = checked_sql.removeprefix(facts.header())
            execution = sql_check(
                context.source, context.student, target=facts.target, sql=headerless
            )
            result = to_sql(
                context.student, dialect=dialect, certificate=replace(facts, execution=execution)
            )
        except UserError as error:
            return JSONResponse(
                status_code=422, content={"error": error.what, "next_step": error.next_step}
            )
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content=error.detail)
        return Response(content=result, media_type="application/sql")

    return router


def workspace_router(runtime: WorkspaceRuntime, *, max_rows: int, dev_states: bool) -> APIRouter:
    """Assemble the table, labelling, inspection and export HTTP surfaces."""
    router = APIRouter()
    router.include_router(table_router(runtime, max_rows=max_rows, dev_states=dev_states))
    router.include_router(label_router(runtime, dev_states=dev_states))
    router.include_router(inspection_router(runtime, dev_states=dev_states))
    router.include_router(workspace_export_router(runtime))
    return router


def mutation_result(runtime: WorkspaceRuntime, *, dev_states: bool) -> WorkspaceState:
    """Queue current inputs before returning the public state."""
    runtime.schedule()
    return workspace_state(runtime, dev_states=dev_states)


def table_router(runtime: WorkspaceRuntime, *, max_rows: int, dev_states: bool) -> APIRouter:
    """Load and page source rows and declare the target."""
    router = APIRouter()
    workspace = runtime.workspace

    @router.post("/table")
    async def load_table(request: Request) -> WorkspaceState:
        data, name = await table_upload(request)
        workspace.load(data, name, max_rows=max_rows)
        return mutation_result(runtime, dev_states=dev_states)

    @router.get("/table")
    async def page_table(
        page: Annotated[int, Query(ge=0)] = 0,
        size: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> TablePage:
        table = workspace.require_table()
        frame = table.frame.iloc[page * size : (page + 1) * size].copy()
        if workspace.store is not None:
            frame[workspace.store.target] = None
        rows = TypeAdapter(list[dict[str, Cell]]).validate_python(
            frame.astype(object)
            .where(frame.notna() & ~frame.isin([float("inf"), -float("inf")]), None)
            .to_dict(orient="records")
        )
        return TablePage(
            rows=rows,
            row_ids=frame.index.tolist(),
            columns=[ColumnInfo.model_validate(column) for column in table.columns],
            total=len(table.frame),
            source_rows=table.source_rows,
            page=page,
            size=size,
        )

    @router.post("/target")
    async def target(body: TargetInput) -> WorkspaceState:
        if body.classes:
            workspace.set_target(body.target, body.classes)
        else:
            workspace.set_target_from_column(body.target)
        return mutation_result(runtime, dev_states=dev_states)

    return router


def label_router(runtime: WorkspaceRuntime, *, dev_states: bool) -> APIRouter:
    """Edit labels and model inputs while preserving blind evaluation."""
    router = APIRouter()
    workspace = runtime.workspace

    @router.put("/labels/{row_id}")
    async def label(row_id: int, body: LabelInput) -> WorkspaceState:
        workspace.set_label(row_id, body.label, body.mode)
        return mutation_result(runtime, dev_states=dev_states)

    @router.post("/undo")
    async def undo() -> WorkspaceState:
        workspace.undo()
        return mutation_result(runtime, dev_states=dev_states)

    @router.get("/eval/next")
    async def eval_next() -> EvalNext:
        return EvalNext(row_id=workspace.next_eval())

    @router.put("/columns/{name}/excluded")
    async def exclusion(name: str, body: ExclusionInput) -> WorkspaceState:
        workspace.exclude(name, excluded=body.excluded)
        return mutation_result(runtime, dev_states=dev_states)

    @router.put("/threshold")
    async def threshold(body: ThresholdInput) -> WorkspaceState:
        workspace.set_threshold(body.threshold)
        return mutation_result(runtime, dev_states=dev_states)

    return router


def inspection_router(runtime: WorkspaceRuntime, *, dev_states: bool) -> APIRouter:
    """Expose current state, measurements, sessions and refit events."""
    router = APIRouter()
    workspace = runtime.workspace

    @router.get("/state")
    async def get_state() -> WorkspaceState:
        return workspace_state(runtime, dev_states=dev_states)

    @router.post("/distill")
    async def distill(body: DistillInput) -> Distilled:
        if runtime.failure is not None:
            raise runtime.failure
        student = workspace.distill(body.max_depth)
        lines = leaf_summary(student, workspace.require_table().frame)
        return Distilled(
            leaf_summary=[LeafLine.model_validate(line) for line in lines],
            disagreements=disagreements(student, workspace.require_proposals()),
            generation=workspace.generation,
        )

    @router.get("/audit")
    async def audit() -> Audit:
        hints = find_leaks(workspace.require_table(), workspace.require_store())
        return Audit(leaks=[LeakHint.model_validate(hint) for hint in hints])

    @router.get("/suspects")
    async def suspects() -> Suspects:
        ranked = await asyncio.wrap_future(
            runtime.worker.audit(workspace.require_table(), workspace.require_store())
        )
        return Suspects(suspects=[Suspect.model_validate(suspect) for suspect in ranked])

    @router.get("/session")
    async def session() -> Response:
        return Response(workspace.require_store().to_json(), media_type="application/json")

    @router.get("/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(
            event_stream(runtime),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def workspace_export_router(runtime: WorkspaceRuntime) -> APIRouter:
    """Export the current rule with measured provenance and full-source SQL identity."""
    router = APIRouter()
    workspace = runtime.workspace

    @router.get("/export")
    async def export(
        export_format: Annotated[ExportFormat, Query(alias="format")] = "sql",
        dialect: Dialect = "duckdb",
    ) -> Response:
        if runtime.failure is not None:
            raise runtime.failure
        artifact = export_artifact(
            workspace, fake=runtime.fake_teacher, export_format=export_format, dialect=dialect
        )
        if isinstance(artifact, dict):
            return JSONResponse(artifact)
        return Response(artifact, media_type=EXPORT_MEDIA_TYPES[export_format])

    return router


def export_artifact(
    workspace: Workspace, *, fake: bool, export_format: ExportFormat, dialect: Dialect
) -> str | dict[str, str]:
    """Render the current rule after proving its SQL on every source row.

    dbt exports are project-relative paths mapped to file contents.
    """
    if export_format == "dbt":
        try:
            validate_names("source_data", workspace.require_store().target)
        except UserError as error:
            raise ApiError(error.what, error.next_step, status_code=422) from error
    facts = workspace.certificate(export_metadata(fake=fake))
    student = workspace.student
    if student is None:
        msg = "Distil the current rule before exporting."
        raise WorkspaceError(msg)
    checked = to_sql(student, dialect="duckdb", certificate=facts).removeprefix(facts.header())
    execution = sql_check_data(workspace.data, student, target=facts.target, sql=checked)
    facts = replace(facts, execution=execution)
    if export_format == "python":
        return facts.header().replace("-- ", "# ") + to_python(student)
    if export_format == "json":
        return to_json(student, certificate=facts)
    if export_format == "dbt":
        try:
            return to_dbt(student, source="source_data", certificate=facts, dialect=dialect)
        except ValueError as error:
            raise ApiError(str(error), status_code=422) from error
    return to_sql(student, dialect=dialect, certificate=facts)
