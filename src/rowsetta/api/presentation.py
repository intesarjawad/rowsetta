import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from importlib.metadata import version

from rowsetta.api.errors import error_body
from rowsetta.api.runtime import WorkspaceRuntime
from rowsetta.api.schemas import ErrorBody, Evaluation, WorkspaceState
from rowsetta.core.workspace import ExportMetadata

CHECKPOINT_SHA256 = "bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0"


def export_metadata(*, fake: bool) -> ExportMetadata:
    """Read shell provenance explicitly; test teacher exports identify their source."""
    return ExportMetadata(
        datetime.now(UTC).date(),
        version("rowsetta"),
        "fake" if fake else version("tabicl"),
        "not applicable (fake teacher)" if fake else CHECKPOINT_SHA256,
    )


async def event_stream(runtime: WorkspaceRuntime) -> AsyncIterator[str]:
    """Frame progress as SSE, retaining cancellation on disconnect."""
    async for event in runtime.events():
        if event is None:
            yield ": connected\n\n"
        else:
            yield f"event: {event.name}\ndata: {json.dumps(event.data)}\n\n"


def workspace_state(runtime: WorkspaceRuntime, *, dev_states: bool) -> WorkspaceState:
    """Hide reserved evaluation predictions in every general workspace response."""
    workspace = runtime.workspace
    store, proposals = workspace.store, workspace.proposals
    hidden = set(store.eval_served) if store is not None else set[int]()
    evaluation = workspace.evaluation()
    return WorkspaceState(
        loaded=workspace.table is not None,
        file_name=workspace.source.file_name if workspace.source is not None else None,
        notice=workspace.notice,
        target=store.target if store is not None else None,
        classes=list(store.classes) if store is not None else [],
        human=store.human if store is not None else {},
        eval_count=len(store.eval) if store is not None else 0,
        threshold=store.threshold if store is not None else 0,
        excluded_columns=sorted(store.excluded_columns) if store is not None else [],
        generation=workspace.generation,
        refit_generation=proposals.generation if proposals is not None else None,
        proposals={row: label for row, label in proposals.label.items() if row not in hidden}
        if proposals is not None
        else {},
        confidence={row: value for row, value in proposals.confidence.items() if row not in hidden}
        if proposals is not None
        else {},
        abstained=sorted(proposals.abstained - hidden) if proposals is not None else [],
        missing=workspace.missing_labels() if store is not None else {},
        next_row=workspace.next_human() if store is not None else None,
        evaluation=Evaluation.model_validate(evaluation) if evaluation is not None else None,
        failure=ErrorBody.model_validate(error_body(runtime.failure))
        if runtime.failure is not None
        else None,
        dev_states=dev_states,
    )
