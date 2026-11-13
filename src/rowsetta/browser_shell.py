"""In-memory browser shell over the same workspace used by the local app."""

import json
from dataclasses import asdict, replace
from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from rowsetta.core.distill import disagreements, leaf_summary
from rowsetta.core.errors import UserError, WorkspaceError
from rowsetta.core.export.sql import NotExecuted, to_sql
from rowsetta.core.features import teacher_frame
from rowsetta.core.teacher import Teacher, predict_table, proposals_from_proba
from rowsetta.core.workspace import ExportMetadata, Workspace

BROWSER_MAX_ROWS = 2_000
BROWSER_MAX_BYTES = 50_000_000
MAX_FIT_ROWS = 5_000
MAX_FIT_FEATURES = 100
MAX_FIT_CELLS = 20_000


def within_browser_fit_limit(n_rows: int, n_features: int) -> bool:
    """Check the reviewed forecast-web limits before a full-model refit."""
    return (
        0 <= n_rows <= MAX_FIT_ROWS
        and 0 <= n_features <= MAX_FIT_FEATURES
        and n_rows * n_features <= MAX_FIT_CELLS
    )


class BrowserRequest(BaseModel):
    """Validate worker messages before any workspace mutation."""

    action: Literal[
        "state",
        "table",
        "target",
        "label",
        "undo",
        "eval",
        "exclude",
        "threshold",
        "distill",
        "audit",
        "export",
        "session",
        "load",
    ]
    page: int = Field(default=0, ge=0)
    size: int = Field(default=100, ge=1, le=1000)
    target: str = Field(default="species", min_length=1)
    classes: tuple[str, ...] = ("Adelie", "Chinstrap", "Gentoo")
    row: int = Field(default=0, ge=0)
    label: str | None = None
    mode: Literal["human", "eval"] = "human"
    column: str = ""
    excluded: bool = False
    threshold: float = Field(default=0.6, ge=0, le=1)
    max_depth: int = Field(default=4, ge=1, le=6)
    format: Literal["sql", "dbt", "python", "json"] = "sql"
    dialect: Literal["duckdb", "postgres", "sqlite"] = "duckdb"
    csv: str = ""
    file_name: str = "data.csv"


class BrowserPrediction(BaseModel):
    """Validate asynchronous WebGPU output before publishing proposals."""

    generation: int
    classes: tuple[str, ...]
    probabilities: list[list[float]]


class BrowserShell:
    """Own a tab's workspace, leaving runtime loading and messages to JavaScript."""

    def __init__(self, teacher: Teacher | None, metadata: ExportMetadata) -> None:
        self.workspace = Workspace(max_bytes=BROWSER_MAX_BYTES)
        self.teacher = teacher
        self.metadata = metadata

    def state(self) -> dict[str, object]:
        """Hide all served evaluation rows, including unlabelled reserved rows."""
        w = self.workspace
        store, proposals = w.store, w.proposals
        hidden = set(store.eval_served) if store else set[int]()
        evaluation = w.evaluation()
        return {
            "loaded": w.table is not None,
            "file_name": w.source.file_name if w.source is not None else None,
            "notice": w.notice
            or "Browser labels live in memory and are lost when you reload or close this tab.",
            "target": store.target if store else None,
            "classes": store.classes if store else (),
            "human": store.human if store else {},
            "eval_count": len(store.eval) if store else 0,
            "threshold": store.threshold if store else 0,
            "excluded_columns": sorted(store.excluded_columns) if store else [],
            "generation": w.generation,
            "refit_generation": proposals.generation if proposals else None,
            "proposals": {r: v for r, v in proposals.label.items() if r not in hidden}
            if proposals
            else {},
            "confidence": {r: v for r, v in proposals.confidence.items() if r not in hidden}
            if proposals
            else {},
            "abstained": sorted(proposals.abstained - hidden) if proposals else [],
            "missing": w.missing_labels() if store else {},
            "next_row": w.next_human() if store else None,
            "evaluation": asdict(evaluation) if evaluation else None,
            "failure": None,
            "dev_states": False,
        }

    def table_page(self, page: int, size: int) -> dict[str, object]:
        """Mask source target values even before the teacher finishes loading."""
        w = self.workspace
        table = w.require_table()
        frame = table.frame.iloc[page * size : (page + 1) * size].copy()
        if w.store:
            frame[w.store.target] = None
        return {
            "rows": frame.astype(object)
            .where(frame.notna() & ~frame.isin([float("inf"), -float("inf")]), None)
            .to_dict(orient="records"),
            "row_ids": frame.index.tolist(),
            "columns": [asdict(c) for c in table.columns],
            "total": len(table.frame),
            "source_rows": table.source_rows,
            "page": page,
            "size": size,
        }

    def refit(self) -> None:
        """Only human rows train the teacher; evaluation rows remain predictions."""
        w = self.workspace
        if self.teacher is not None and w.store is not None and not w.missing_labels():
            w.publish(predict_table(self.teacher, w.require_table(), w.store), w.generation)

    def refit_input(self) -> str:
        """Send only human labels to the tab-local WebGPU worker."""
        w = self.workspace
        if (
            w.store is None
            or w.missing_labels()
            or (w.proposals is not None and w.proposals.generation == w.generation)
        ):
            return "null"
        labels = w.store.training_rows()
        frame = teacher_frame(w.require_table(), w.store).frame.loc[list(w.store.source.row_ids())]
        if not within_browser_fit_limit(len(labels), len(frame.columns)):
            message = "This fit exceeds the browser model's 20,000-cell limit."
            raise WorkspaceError(
                message,
                "Use fewer labelled rows or features, or open the table in the local app.",
            )
        frame = frame.astype(object).where(
            frame.notna() & ~frame.isin([float("inf"), -float("inf")]), None
        )
        return json.dumps(
            {
                "generation": w.generation,
                "train": frame.loc[list(labels)].values.tolist(),
                "labels": list(labels.values()),
                "test": frame.values.tolist(),
            }
        )

    def publish_refit(self, message: str) -> None:
        """Reject stale or malformed probabilities at the worker boundary."""
        result = BrowserPrediction.model_validate_json(message)
        w = self.workspace
        if result.generation != w.generation:
            message = "Model result has a stale generation."
            raise ValueError(message)
        proposals = proposals_from_proba(
            np.asarray(result.probabilities, dtype=np.float64),
            result.classes,
            w.require_store(),
            generation=result.generation,
        )
        w.publish(proposals, result.generation)

    def mutate(self, request: BrowserRequest) -> None:
        """Change only inputs; all derived results are invalidated by Workspace."""
        w = self.workspace
        match request.action:
            case "load":
                w.load(request.csv.encode(), request.file_name, max_rows=BROWSER_MAX_ROWS)
            case "target":
                if not request.classes:
                    msg = "Existing-column labelling is a local-app feature."
                    raise WorkspaceError(
                        msg, "Name a target and its classes to teach from scratch."
                    )
                w.set_target(request.target, request.classes)
            case "label":
                w.set_label(request.row, request.label, request.mode)
            case "undo":
                w.undo()
            case "exclude":
                w.exclude(request.column, excluded=request.excluded)
            case "threshold":
                w.set_threshold(request.threshold)
            case _:
                msg = f"Not an input mutation: {request.action}"
                raise ValueError(msg)

    def execute(self, request: BrowserRequest, *, refit: bool = True) -> object:
        """Apply one validated command and return its public result."""
        w = self.workspace
        result: object
        match request.action:
            case "table":
                result = self.table_page(request.page, request.size)
            case "eval":
                result = {"row_id": w.next_eval()}
            case "distill":
                student = w.distill(request.max_depth)
                result = {
                    "leaf_summary": [
                        asdict(line) for line in leaf_summary(student, w.require_table().frame)
                    ],
                    "disagreements": disagreements(student, w.require_proposals()),
                    "generation": w.generation,
                }
            case "audit":
                from rowsetta.core.leaks import find_leaks  # noqa: PLC0415 -- Optional route.

                result = {
                    "leaks": [asdict(h) for h in find_leaks(w.require_table(), w.require_store())]
                }
            case "export":
                result = self.export(request)
            case "session":
                result = w.require_store().to_json()
            case _:
                if request.action != "state":
                    self.mutate(request)
                    if refit:
                        self.refit()
                result = self.state()
        return result

    def export(self, request: BrowserRequest) -> object:
        """Export shared rules with an honest browser execution certificate."""
        w = self.workspace
        if request.format == "dbt":
            from rowsetta.core.export.dbt import validate_names  # noqa: PLC0415 -- Optional route.

            validate_names("source_data", w.require_store().target)
        facts = replace(w.certificate(self.metadata), execution=NotExecuted("browser demo"))
        student = w.student
        if student is None:
            msg = "Distil the current rule before exporting."
            raise WorkspaceError(msg)
        match request.format:
            case "json":
                from rowsetta.core.export.json import to_json  # noqa: PLC0415 -- Optional route.

                return to_json(student, certificate=facts)
            case "python":
                from rowsetta.core.export.python import to_python  # noqa: PLC0415 -- Optional route.

                return facts.header().replace("-- ", "# ") + to_python(student)
            case "dbt":
                from rowsetta.core.export.dbt import to_dbt  # noqa: PLC0415 -- Optional route.

                return to_dbt(
                    student, source="source_data", certificate=facts, dialect=request.dialect
                )
            case "sql":
                return to_sql(student, dialect=request.dialect, certificate=facts)

    def call(self, message: str, *, refit: bool = True) -> str:
        """Keep structured recovery errors intact across the worker boundary."""
        try:
            request = BrowserRequest.model_validate_json(message)
            result = self.execute(request, refit=refit)
            pending = "null"
            if not refit and request.action in {
                "load",
                "target",
                "label",
                "undo",
                "exclude",
                "threshold",
            }:
                pending = self.refit_input()
            return json.dumps({"ok": True, "value": result, "refit": pending}, allow_nan=False)
        except UserError as error:
            return json.dumps(
                {"ok": False, "error": {"error": error.what, "next_step": error.next_step}}
            )


def browser_metadata(today: str, *, full_model: bool = False) -> ExportMetadata:
    """Use the browser-supplied date rather than hiding a clock in core."""
    return ExportMetadata(
        date.fromisoformat(today),
        "0.1.0",
        "TabICLv2 (WebGPU)" if full_model else "lite model (random forest), not TabICLv2",
        "bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0"
        if full_model
        else "not applicable (lite model)",
    )
