"""Re-export a saved session without the browser, for scripts and CI."""

import json
import shlex
from pathlib import Path
from typing import override

from pydantic import ValidationError

from rowsetta.api.routes import ExportFormat, export_artifact
from rowsetta.api.schemas import DistillInput
from rowsetta.app import local_teacher, row_limit
from rowsetta.core.errors import NeedLabelsError, UserError
from rowsetta.core.export.dbt import validate_names
from rowsetta.core.export.sql import Dialect
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.teacher import predict_table
from rowsetta.core.workspace import SessionPersistence, Workspace
from rowsetta.teachers.fake import FakeTeacher


class SavedSession(SessionPersistence):
    """Restore one session file for exactly the source rows it was saved with."""

    def __init__(self, store: LabelStore, csv: Path) -> None:
        self.store = store
        self.csv = csv

    @override
    def open(self, data: bytes, source: SourceRef) -> tuple[LabelStore, None]:
        if source.sha256 != self.store.source.sha256:
            message = f"`{self.csv}` changed since the session was saved."
            recovery = shlex.join(["rowsetta", "open", str(self.csv)])
            raise UserError(message, f"{recovery}, then label it again")
        if self.store.source.model_copy(update={"file_name": source.file_name}) != source:
            message = "The saved session uses a different source row sample."
            raise UserError(message, "Set ROWSETTA_MAX_ROWS to the limit used when saving.")
        return self.store, None

    @override
    def save(self, store: LabelStore) -> None:
        """Leave the session file as saved; exports never write to it."""


def export_session(session: Path, *, export_format: ExportFormat, dialect: Dialect) -> str:
    """Refit the teacher on the saved labels, distil the rule and render it.

    The CSV is the sidecar's `source.file_name`, relative to the sidecar, and must still
    match its SHA-256. dbt exports print as a JSON map of project files.
    """
    store = _read_session(session)
    if export_format == "dbt":
        validate_names("source_data", store.target)
    csv = session.parent / store.source.file_name
    try:
        data = csv.read_bytes()
    except OSError as error:
        message = f"Could not read `{csv}`, the CSV this session labels: {error.strerror}."
        recovery = shlex.join(["rowsetta", "export", str(session)])
        raise UserError(message, f"{recovery} once the CSV is back in place") from error
    workspace = Workspace(SavedSession(store, csv))
    workspace.load(data, csv.name, max_rows=row_limit(), display_name=str(csv))
    missing = workspace.missing_labels()
    if missing:
        raise NeedLabelsError(missing)
    teacher = local_teacher()
    proposals = predict_table(teacher, workspace.require_table(), workspace.require_store())
    workspace.publish(proposals, workspace.generation)
    workspace.distill(DistillInput().max_depth)
    artifact = export_artifact(
        workspace,
        fake=isinstance(teacher, FakeTeacher),
        export_format=export_format,
        dialect=dialect,
    )
    if isinstance(artifact, dict):
        return json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    return artifact


def _read_session(session: Path) -> LabelStore:
    try:
        text = session.read_text(encoding="utf-8")
    except UnicodeError as error:
        message = f"`{session}` is not a saved session: expected UTF-8 JSON."
        raise UserError(
            message,
            "rowsetta open <the CSV>, then label it again to save a new session",
        ) from error
    except OSError as error:
        message = f"Could not read `{session}`: {error.strerror}."
        raise UserError(message, "rowsetta export <a saved .rowsetta.json>") from error
    try:
        return LabelStore.from_json(text)
    except ValidationError as error:
        message = f"`{session}` is not a saved session: {error.error_count()} invalid fields."
        raise UserError(
            message, "rowsetta open <the CSV>, then label it again to save a new session"
        ) from error
