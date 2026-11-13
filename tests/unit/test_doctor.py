import errno
import hashlib
import io
import shutil
import socket
import subprocess
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn

from rowsetta import cli
from rowsetta.api.errors import ModelUnavailableError
from rowsetta.core.errors import UserError
from rowsetta.doctor import DownloadProgress, doctor, fetch_checkpoint
from rowsetta.teachers import checkpoint
from rowsetta.teachers.fake import FakeTeacher

PINNED = b"pinned checkpoint bytes"
RETRY = "rowsetta demo --no-browser"


class FakeHub:
    """A local cache directory standing in for the pinned hub revision."""

    def __init__(
        self, cached: Path, *, failure: BaseException | None = None, served: bytes = PINNED
    ) -> None:
        self.cached = cached
        self.failure = failure
        self.served = served
        self.downloads = 0

    def try_to_load_from_cache(self, repo_id: str, filename: str, *, revision: str) -> str | None:
        assert (repo_id, filename, revision) == (
            checkpoint.REPO_ID,
            checkpoint.FILENAME,
            checkpoint.REVISION,
        )
        return str(self.cached) if self.cached.exists() else None

    def hf_hub_download(
        self,
        repo_id: str,
        filename: str,
        *,
        revision: str,
        tqdm_class: type[DownloadProgress],
    ) -> str:
        assert (repo_id, filename, revision) == (
            checkpoint.REPO_ID,
            checkpoint.FILENAME,
            checkpoint.REVISION,
        )
        self.downloads += 1
        if self.failure is not None:
            raise self.failure
        progress = tqdm_class(total=len(self.served), unit="B")
        self.cached.write_bytes(self.served)
        progress.update(len(self.served))
        progress.close()
        return str(self.cached)


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkpoint, "SHA256", hashlib.sha256(PINNED).hexdigest())
    monkeypatch.setattr(checkpoint, "SIZE_BYTES", len(PINNED))
    monkeypatch.setenv("ROWSETTA_DEVICE", "cpu")


def test_fix_replaces_a_corrupted_cached_checkpoint(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")
    hub.cached.write_bytes(b"corrupted")
    report = io.StringIO()

    doctor(fix=True, hub=hub, out=report)

    assert hub.cached.read_bytes() == PINNED
    assert hub.downloads == 1
    assert f"sha256      {checkpoint.SHA256} (pinned)" in report.getvalue()


def test_fix_removes_the_corrupted_blob_behind_a_cache_link(tmp_path: Path) -> None:
    blob = tmp_path / "blobs" / "corrupted"
    blob.parent.mkdir()
    blob.write_bytes(b"corrupted")
    hub = FakeHub(tmp_path / "model.ckpt")
    hub.cached.symlink_to(blob)

    doctor(fix=True, hub=hub, out=io.StringIO())

    assert not blob.exists()
    assert hub.cached.read_bytes() == PINNED


def test_report_without_fix_keeps_the_file_and_names_the_repair(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")
    hub.cached.write_bytes(b"corrupted")
    report = io.StringIO()

    with pytest.raises(ModelUnavailableError) as raised:
        doctor(fix=False, hub=hub, out=report)

    assert raised.value.next_step == "rowsetta doctor --fix"
    assert hub.cached.read_bytes() == b"corrupted"
    assert hub.downloads == 0
    digest = hashlib.sha256(b"corrupted").hexdigest()
    assert f"sha256      {digest} (expected {checkpoint.SHA256})" in report.getvalue()


def test_report_names_the_device_and_a_missing_checkpoint(tmp_path: Path) -> None:
    report = io.StringIO()

    with pytest.raises(ModelUnavailableError):
        doctor(fix=False, hub=FakeHub(tmp_path / "model.ckpt"), out=report)

    lines = report.getvalue().splitlines()
    assert lines[0].startswith("torch       ")
    assert lines[1].startswith("tabicl      ")
    assert lines[2:] == ["device      cpu (ROWSETTA_DEVICE)", "checkpoint  not downloaded"]


def test_fix_downloads_a_missing_checkpoint(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")

    doctor(fix=True, hub=hub, out=io.StringIO())

    assert hub.cached.read_bytes() == PINNED


def test_fix_keeps_a_verified_checkpoint(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")
    hub.cached.write_bytes(PINNED)

    doctor(fix=True, hub=hub, out=io.StringIO())

    assert hub.downloads == 0


def test_failed_download_names_the_retry(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt", failure=ConnectionError("network unreachable"))

    with pytest.raises(UserError) as raised:
        doctor(fix=True, hub=hub, out=io.StringIO())

    assert "network unreachable" in raised.value.what
    assert raised.value.next_step.startswith("rowsetta doctor --fix")


def test_download_progress_is_one_line_with_bytes_and_percent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    progress = DownloadProgress(total=2_000_000, unit="B")
    progress.update(500_000)
    progress.update(1_500_000)
    progress.close()

    assert capsys.readouterr().err == (
        f"Downloading {checkpoint.FILENAME}: 2,000,000 of 2,000,000 bytes (100%)\n"
    )


def test_xet_transfer_updates_leave_the_one_line_on_bytes_written(
    capsys: pytest.CaptureFixture[str],
) -> None:
    progress = DownloadProgress(total=2_000, unit="B")
    progress.update(2_000)
    progress.update_transfer(1_200)
    progress.set_transfer_postfix_str("4.1MB/s", refresh=False)
    progress.close()

    assert capsys.readouterr().err == (
        f"Downloading {checkpoint.FILENAME}: 2,000 of 2,000 bytes (100%)\n"
    )


def test_download_progress_starts_no_multiprocessing_resource_tracker() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from multiprocessing import resource_tracker
from rowsetta.doctor import DownloadProgress
DownloadProgress(total=1, unit="B").close()
assert resource_tracker._resource_tracker._pid is None
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def launch_demo(hub: FakeHub, monkeypatch: pytest.MonkeyPatch, home: Path) -> list[object]:
    served: list[object] = []
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ROWSETTA_TEACHER", raising=False)
    with socket.create_server(("127.0.0.1", 0)) as available:
        port = available.getsockname()[1]
    monkeypatch.setattr(sys, "argv", ["rowsetta", *RETRY.split()[1:], "--port", str(port)])
    monkeypatch.setattr(cli, "fetch_checkpoint", partial(fetch_checkpoint, hub=hub))
    monkeypatch.setattr(cli, "local_teacher", FakeTeacher)

    def serve(server: uvicorn.Server, **_options: object) -> None:
        served.append(server.config.app)

    monkeypatch.setattr(uvicorn.Server, "run", serve)
    cli.main()
    return served


def test_first_run_downloads_the_checkpoint_then_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")

    served = launch_demo(hub, monkeypatch, tmp_path)

    output = capsys.readouterr()
    assert hub.downloads == 1
    assert hub.cached.read_bytes() == PINNED
    assert len(served) == 1
    assert output.out.startswith("Loaded penguins.csv\n")
    assert output.err.splitlines() == [
        f"The model is 0.0 MB; it downloads once from huggingface.co/{checkpoint.REPO_ID}.",
        f"Downloading {checkpoint.FILENAME}: 23 of 23 bytes (100%)",
    ]


def test_second_run_serves_from_the_cache_without_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")
    launch_demo(hub, monkeypatch, tmp_path)
    capsys.readouterr()

    served = launch_demo(hub, monkeypatch, tmp_path)

    assert hub.downloads == 1
    assert len(served) == 1
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("Please check your connection and try again"),
        RuntimeError("connection reset while reconstructing the file"),
    ],
    ids=["hub-lookup", "transfer"],
)
def test_lost_network_names_the_retry_and_keeps_nothing(tmp_path: Path, failure: Exception) -> None:
    hub = FakeHub(tmp_path / "model.ckpt", failure=failure)

    with pytest.raises(UserError) as raised:
        fetch_checkpoint(offline=False, retry=RETRY, hub=hub)

    assert raised.value.what == f"Could not download the model: {failure}"
    assert raised.value.next_step == f"{RETRY} once the network is reachable"
    assert not hub.cached.exists()


def test_checksum_mismatch_deletes_the_download(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt", served=b"tampered checkpoint byte")

    with pytest.raises(UserError) as raised:
        fetch_checkpoint(offline=False, retry=RETRY, hub=hub)

    assert raised.value.what == "The downloaded model failed its checksum and was deleted."
    assert raised.value.next_step == RETRY
    assert not hub.cached.exists()


def test_too_little_disk_space_fails_before_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")
    monkeypatch.setattr(checkpoint, "SIZE_BYTES", 7_000_000)

    def nearly_full(_path: object) -> SimpleNamespace:
        return SimpleNamespace(free=5_000_000)

    monkeypatch.setattr(shutil, "disk_usage", nearly_full)

    with pytest.raises(UserError) as raised:
        fetch_checkpoint(offline=False, retry=RETRY, hub=hub)

    assert raised.value.what.startswith("The model needs 7.0 MB, but only 5.0 MB is free in ")
    assert raised.value.next_step == f"{RETRY} after freeing space there"
    assert hub.downloads == 0


def test_a_disk_that_fills_during_the_download_names_the_space(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt", failure=OSError(errno.ENOSPC, "No space left on device"))

    with pytest.raises(UserError) as raised:
        fetch_checkpoint(offline=False, retry=RETRY, hub=hub)

    assert raised.value.what.startswith("The model needs ")
    assert raised.value.next_step == f"{RETRY} after freeing space there"
    assert not hub.cached.exists()


def test_interrupted_download_names_the_retry(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt", failure=KeyboardInterrupt())

    with pytest.raises(UserError) as raised:
        fetch_checkpoint(offline=False, retry=RETRY, hub=hub)

    assert raised.value.what == "The model download was interrupted; no partial file was kept."
    assert raised.value.next_step == RETRY
    assert not hub.cached.exists()


def test_offline_first_run_fails_without_downloading(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")

    with pytest.raises(UserError) as raised:
        fetch_checkpoint(offline=True, retry=RETRY, hub=hub)

    assert raised.value.what == "The model is not downloaded yet, and --offline skips the download."
    assert raised.value.next_step == "rowsetta doctor --fix while online"
    assert hub.downloads == 0


def test_offline_run_uses_a_cached_checkpoint(tmp_path: Path) -> None:
    hub = FakeHub(tmp_path / "model.ckpt")
    hub.cached.write_bytes(PINNED)

    fetch_checkpoint(offline=True, retry=RETRY, hub=hub)

    assert hub.downloads == 0
