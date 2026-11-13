import errno
import importlib
import logging
import os
import shutil
import sys
import threading
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Protocol, TextIO, override

import huggingface_hub
from huggingface_hub import constants
from tqdm import tqdm

from rowsetta.api.errors import ModelUnavailableError
from rowsetta.core.errors import BYTES_PER_MB, UserError
from rowsetta.teachers import checkpoint

LABEL_WIDTH = 12

# The stubs type a bar without an iterable as tqdm[NoReturn]; the runtime class takes no subscript.
if TYPE_CHECKING:
    ProgressBar = tqdm[NoReturn]
else:
    ProgressBar = tqdm


# Plain tqdm, not the hub's subclass, which the hub switches off when stderr is not a terminal.
class DownloadProgress(ProgressBar):
    """One line with bytes and percent: rewritten on a terminal, printed once in logs."""

    # tqdm's default lock is a multiprocessing one, which leaks a semaphore when the server stops.
    _lock = threading.RLock()

    def update_transfer(self, _network_bytes: int) -> None:
        """Count only bytes written, so a Xet download shares this one line with its transfer."""

    def set_transfer_postfix_str(self, _postfix: str, **_options: object) -> None:
        """Leave out the transfer rate, which the line does not show."""

    @override
    def display(self, msg: str | None = None, pos: int | None = None) -> None:
        """Write the progress line; tqdm adds the final newline when the download closes."""
        terminal = sys.stderr.isatty()
        # tqdm passes pos=0 only from close(), so logs get the finished count alone.
        if not terminal and pos != 0:
            return
        done, total = int(self.n), int(self.total or 0)
        percent = done * 100 // total if total else 0
        prefix = "\r" if terminal else ""
        sys.stderr.write(
            f"{prefix}Downloading {checkpoint.FILENAME}: {done:,} of {total:,} bytes ({percent}%)"
        )


class CheckpointHub(Protocol):
    """The hub's offline cache lookup and its pinned download."""

    def try_to_load_from_cache(self, repo_id: str, filename: str, *, revision: str) -> object:
        """Return the cached path as a string; any other value means it is absent."""
        ...

    def hf_hub_download(
        self,
        repo_id: str,
        filename: str,
        *,
        revision: str,
        tqdm_class: type[DownloadProgress],
    ) -> str:
        """Download the file at an immutable revision and return its cached path."""
        ...


def doctor(*, fix: bool, hub: CheckpointHub = huggingface_hub, out: TextIO = sys.stdout) -> None:
    """Report the model runtime and checkpoint, replacing a bad checkpoint when asked.

    Raises ModelUnavailableError when the checkpoint is still missing or corrupt.
    """
    cached = _cached(hub)
    if fix and (cached is None or not checkpoint.is_pinned(*cached)):
        if cached is not None:
            _remove(cached[0])
        cached = _download(hub, retry="rowsetta doctor --fix")
    rows = [("torch", version("torch")), ("tabicl", version("tabicl")), ("device", _device())]
    if cached is None:
        rows.append(("checkpoint", "not downloaded"))
    else:
        path, digest = cached
        status = "pinned" if checkpoint.is_pinned(path, digest) else f"expected {checkpoint.SHA256}"
        rows += [("checkpoint", str(path)), ("sha256", f"{digest} ({status})")]
    out.write("".join(f"{label:<{LABEL_WIDTH}}{value}\n" for label, value in rows))
    if cached is None or not checkpoint.is_pinned(*cached):
        raise ModelUnavailableError


def fetch_checkpoint(*, offline: bool, retry: str, hub: CheckpointHub = huggingface_hub) -> None:
    """Download and verify the pinned checkpoint on first use, so the first run needs no setup.

    A cached file is left for the teacher to verify, so a corrupt one still points to `doctor`.
    `retry` is the command that repeats this launch, named in every failure.
    """
    if _cached_path(hub) is not None:
        return
    if offline:
        message = "The model is not downloaded yet, and --offline skips the download."
        raise UserError(message, "rowsetta doctor --fix while online")
    path, digest = _download(hub, retry=retry)
    if not checkpoint.is_pinned(path, digest):
        _remove(path)
        message = "The downloaded model failed its checksum and was deleted."
        raise UserError(message, retry)


def _cached_path(hub: CheckpointHub) -> Path | None:
    found = hub.try_to_load_from_cache(
        checkpoint.REPO_ID, checkpoint.FILENAME, revision=checkpoint.REVISION
    )
    return Path(found) if isinstance(found, str) else None


def _cached(hub: CheckpointHub) -> tuple[Path, str] | None:
    path = _cached_path(hub)
    return None if path is None else (path, checkpoint.file_sha256(path))


def _remove(path: Path) -> None:
    # The hub cache links the file name to a content blob; both must go.
    path.resolve().unlink()
    path.unlink(missing_ok=True)


def _download(hub: CheckpointHub, *, retry: str) -> tuple[Path, str]:
    """Fetch the pinned file; the hub writes a temporary name and deletes it on any failure."""
    free_bytes = _free_bytes()
    if free_bytes < checkpoint.SIZE_BYTES:
        raise _disk_full(free_bytes, retry)
    sys.stderr.write(
        f"The model is {_megabytes(checkpoint.SIZE_BYTES)} MB; "
        f"it downloads once from huggingface.co/{checkpoint.REPO_ID}.\n"
    )
    # The server suggests setting HF_TOKEN; the pinned public file needs no account.
    logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)
    offline = constants.HF_HUB_OFFLINE
    # The app turns the hub offline at import; this is the one download the user starts.
    constants.HF_HUB_OFFLINE = False
    try:
        path = Path(
            hub.hf_hub_download(
                checkpoint.REPO_ID,
                checkpoint.FILENAME,
                revision=checkpoint.REVISION,
                tqdm_class=DownloadProgress,
            )
        )
    except KeyboardInterrupt as error:
        message = "The model download was interrupted; no partial file was kept."
        raise UserError(message, retry) from error
    # The hub reports one lost connection as OSError, an httpx2 error or a Xet error.
    except Exception as error:
        if isinstance(error, OSError) and error.errno == errno.ENOSPC:
            raise _disk_full(_free_bytes(), retry) from error
        message = f"Could not download the model: {error}"
        raise UserError(message, f"{retry} once the network is reachable") from error
    finally:
        constants.HF_HUB_OFFLINE = offline
    return path, checkpoint.file_sha256(path)


def _free_bytes() -> int:
    cache = Path(constants.HF_HUB_CACHE)
    # The cache directory does not exist before the first download.
    existing = next(directory for directory in (cache, *cache.parents) if directory.exists())
    return shutil.disk_usage(existing).free


def _disk_full(free_bytes: int, retry: str) -> UserError:
    return UserError(
        f"The model needs {_megabytes(checkpoint.SIZE_BYTES)} MB, "
        f"but only {_megabytes(free_bytes)} MB is free in {constants.HF_HUB_CACHE}.",
        f"{retry} after freeing space there",
    )


def _megabytes(size_bytes: int) -> str:
    return f"{size_bytes / BYTES_PER_MB:.1f}"


def _device() -> str:
    requested = os.environ.get("ROWSETTA_DEVICE") or None
    # tabicl resolves device=None with this function, so the report matches what a refit uses.
    devices = importlib.import_module("tabicl._torch_devices")
    resolved = str(devices.resolve_torch_device(requested))
    return f"{resolved} (ROWSETTA_DEVICE)" if requested else f"{resolved} (automatic)"
