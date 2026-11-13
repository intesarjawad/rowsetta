import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from rowsetta.core.errors import UserError
from rowsetta.core.session import LabelStore, SourceRef

STALE_CSV_MESSAGE = "this CSV changed since the session was saved"
SESSIONS_DIR_VARIABLE = "ROWSETTA_SESSIONS_DIR"


def default_data_dir() -> Path:
    """Where uploads and bundled demos keep their sessions; tests point it at a scratch dir."""
    configured = os.environ.get(SESSIONS_DIR_VARIABLE)
    return Path(configured) if configured else Path.home() / ".rowsetta/sessions"


class SessionStorage:
    """Keep managed CSVs and atomic sidecars locally, or use an adjacent local sidecar."""

    def __init__(self, *, data_dir: Path | None = None, source_path: Path | None = None) -> None:
        self.data_dir = data_dir if data_dir is not None else default_data_dir()
        self.source_path = source_path

    def open(self, data: bytes, source: SourceRef) -> tuple[LabelStore | None, str | None]:
        """Store validated uploads and resume only sessions for these exact source rows."""
        path = self._csv_path(source)
        sidecar = path.with_suffix(".rowsetta.json")
        try:
            if self.source_path is None:
                path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(path, data)
            store, notice = self._restore(sidecar, source)
        except UnicodeDecodeError as error:
            message = f"Could not read the session JSON at {sidecar}: invalid UTF-8."
            raise UserError(
                message,
                "Restore a UTF-8 copy of the sidecar, or rename it to keep it "
                "and reopen the CSV without saved labels.",
            ) from error
        except (OSError, ValidationError) as error:
            message = f"Could not open the session beside {path}: {error}"
            raise UserError(
                message,
                "Check directory permissions and the session JSON, then reopen the CSV.",
            ) from error
        return store, notice

    def save(self, store: LabelStore) -> None:
        """Replace the last complete sidecar only after the temporary file is flushed."""
        sidecar = self._csv_path(store.source).with_suffix(".rowsetta.json")
        try:
            _atomic_write(sidecar, store.to_json().encode("utf-8"))
        except OSError as error:
            message = f"Could not save the session: {error}"
            raise UserError(
                message,
                "Check free disk space and directory permissions, then retry the change.",
            ) from error

    def _csv_path(self, source: SourceRef) -> Path:
        name = Path(source.file_name).name
        if name in {"", ".", ".."} or "\\" in name or name != source.file_name:
            message = "The CSV basename is invalid."
            raise UserError(message, "Choose a CSV with a plain file name.")
        return self.source_path or self.data_dir / source.sha256 / name

    @staticmethod
    def _restore(sidecar: Path, source: SourceRef) -> tuple[LabelStore | None, str | None]:
        if not sidecar.exists():
            return None, None
        store = LabelStore.from_json(sidecar.read_text(encoding="utf-8"))
        if store.source.sha256 != source.sha256:
            stamp = datetime.now(UTC).date().isoformat()
            archived = sidecar.with_name(f"{sidecar.stem}.{stamp}.json")
            sequence = 1
            while archived.exists():
                archived = sidecar.with_name(f"{sidecar.stem}.{stamp}.{sequence}.json")
                sequence += 1
            sidecar.rename(archived)
            return None, STALE_CSV_MESSAGE
        if store.source.model_copy(update={"file_name": source.file_name}) != source:
            message = "The saved session uses a different source row sample."
            raise UserError(
                message,
                "Reopen the CSV with the same row limit used when saving the session.",
            )
        store.source = source
        return store, None


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
