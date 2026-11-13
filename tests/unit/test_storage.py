from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from rowsetta.core.errors import UserError
from rowsetta.core.session import LabelStore
from rowsetta.core.workspace import Workspace
from rowsetta.storage import STALE_CSV_MESSAGE, SessionStorage

DATA = b"x,z,target\n1,2,a\n2,3,b\n3,4,a\n4,5,b\n5,6,a\n6,7,b\n"


def open_workspace(directory: Path, *, local_path: Path | None = None) -> Workspace:
    workspace = Workspace(SessionStorage(data_dir=directory, source_path=local_path))
    data = local_path.read_bytes() if local_path else DATA
    workspace.load(data, local_path.name if local_path else "data.csv", max_rows=6)
    return workspace


def sidecar(directory: Path) -> Path:
    return directory / sha256(DATA).hexdigest() / "data.rowsetta.json"


def saved(directory: Path) -> LabelStore:
    return LabelStore.from_json(sidecar(directory).read_text())


def test_managed_storage_saves_every_session_mutation_and_resumes(tmp_path: Path) -> None:
    workspace = open_workspace(tmp_path)
    csv = sidecar(tmp_path).with_name("data.csv")
    assert csv.read_bytes() == DATA
    workspace.set_target("target", ("a", "b"))
    assert saved(tmp_path).target == "target"
    workspace.set_label(0, "a", "human")
    assert saved(tmp_path).human == {0: "a"}
    workspace.set_label(0, None, "human")
    assert saved(tmp_path).human == {}
    workspace.undo()
    assert saved(tmp_path).human == {0: "a"}
    row = workspace.next_eval()
    assert row is not None
    assert saved(tmp_path).current_eval_row == row
    assert saved(tmp_path).eval_served == [row]
    workspace.set_label(row, "b", "eval")
    assert saved(tmp_path).eval == {row: "b"}
    workspace.undo()
    assert saved(tmp_path).current_eval_row == row
    workspace.exclude("z", excluded=True)
    assert saved(tmp_path).excluded_columns == {"z"}
    workspace.set_threshold(0.7)
    assert saved(tmp_path).threshold == 0.7
    restored = open_workspace(tmp_path)
    assert restored.require_store() == workspace.require_store()
    assert restored.next_eval() == row
    assert restored.require_store().source.file_name == csv.name
    assert not list(tmp_path.rglob("*.tmp"))


def test_crash_before_replace_reloads_last_good_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = open_workspace(tmp_path)
    workspace.set_target("target", ("a", "b"))
    workspace.set_label(0, "a", "human")
    last_good = sidecar(tmp_path).read_bytes()
    original_replace = Path.replace

    def crash(path: Path, target: str | Path) -> Path:
        if path.name == "data.rowsetta.json.tmp":
            message = "simulated crash before replace"
            raise OSError(message)
        return original_replace(path, target)

    with monkeypatch.context() as context:
        context.setattr(Path, "replace", crash)
        with pytest.raises(UserError, match="simulated crash"):
            workspace.set_label(1, "b", "human")
    assert sidecar(tmp_path).read_bytes() == last_good
    temporary = sidecar(tmp_path).with_name("data.rowsetta.json.tmp")
    assert LabelStore.from_json(temporary.read_text()).human == {0: "a", 1: "b"}
    assert open_workspace(tmp_path).require_store().human == {0: "a"}


def test_changed_local_csv_archives_sidecar_without_applying_labels(tmp_path: Path) -> None:
    path = tmp_path / "local.csv"
    path.write_bytes(DATA)
    workspace = open_workspace(tmp_path / "managed", local_path=path)
    workspace.set_target("target", ("a", "b"))
    workspace.set_label(0, "a", "human")
    adjacent = path.with_suffix(".rowsetta.json")
    previous = adjacent.read_bytes()
    path.write_bytes(DATA.replace(b"1,2,a", b"9,2,a"))
    restored = open_workspace(tmp_path / "managed", local_path=path)
    assert restored.store is None
    assert restored.notice == STALE_CSV_MESSAGE
    stamp = datetime.now(UTC).date().isoformat()
    archive = tmp_path / f"local.rowsetta.{stamp}.json"
    assert archive.read_bytes() == previous
    assert not adjacent.exists()
    assert not (tmp_path / "managed").exists()
    restored.set_target("target", ("a", "b"))
    assert restored.require_store().human == {}
    path.write_bytes(DATA)
    assert open_workspace(tmp_path, local_path=path).store is None
    assert archive.read_bytes() == previous
    assert (tmp_path / f"local.rowsetta.{stamp}.1.json").exists()


def test_same_basename_different_bytes_are_isolated(tmp_path: Path) -> None:
    first = open_workspace(tmp_path)
    first.set_target("target", ("a", "b"))
    first.set_label(0, "a", "human")
    other = Workspace(SessionStorage(data_dir=tmp_path))
    changed = DATA.replace(b"1,2,a", b"9,2,a")
    other.load(changed, "data.csv", max_rows=6)
    assert other.store is None
    assert (tmp_path / sha256(changed).hexdigest() / "data.csv").read_bytes() == changed
    assert open_workspace(tmp_path).require_store().human == {0: "a"}


def test_changed_sample_limit_does_not_apply_saved_labels(tmp_path: Path) -> None:
    workspace = open_workspace(tmp_path)
    workspace.set_target("target", ("a", "b"))
    other = Workspace(SessionStorage(data_dir=tmp_path))
    with pytest.raises(UserError, match="different source row sample"):
        other.load(DATA, "data.csv", max_rows=3)
    assert other.table is None
    assert saved(tmp_path).source.sampled_rows is None


def test_invalid_sidecar_does_not_replace_active_session(tmp_path: Path) -> None:
    workspace = open_workspace(tmp_path)
    workspace.set_target("target", ("a", "b"))
    changed = DATA.replace(b"1,2,a", b"9,2,a")
    directory = tmp_path / sha256(changed).hexdigest()
    directory.mkdir()
    invalid = directory / "other.rowsetta.json"
    invalid.write_text("{}")
    with pytest.raises(UserError, match="Could not open the session"):
        workspace.load(changed, "other.csv", max_rows=6)
    workspace.set_label(0, "a", "human")
    assert saved(tmp_path).human == {0: "a"}
    assert invalid.read_text() == "{}"


@pytest.mark.parametrize("name", ["../data.csv", "..", "folder\\data.csv"])
def test_storage_rejects_non_basename_sources(tmp_path: Path, name: str) -> None:
    workspace = Workspace(SessionStorage(data_dir=tmp_path))
    with pytest.raises(UserError, match="basename is invalid"):
        workspace.load(DATA, name, max_rows=6)
    assert list(tmp_path.iterdir()) == []


def test_sessions_dir_variable_moves_managed_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROWSETTA_SESSIONS_DIR", str(tmp_path))
    workspace = Workspace(SessionStorage())
    workspace.load(DATA, "data.csv", max_rows=6)
    workspace.set_target("target", ("a", "b"))
    assert saved(tmp_path).target == "target"


def test_sessions_default_to_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ROWSETTA_SESSIONS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert SessionStorage().data_dir == tmp_path / ".rowsetta/sessions"


@pytest.mark.parametrize("local", [False, True])
def test_non_utf8_sidecar_preserves_bytes_and_names_recovery(
    tmp_path: Path, *, local: bool
) -> None:
    path = tmp_path / "local.csv" if local else None
    if path is not None:
        path.write_bytes(DATA)
    workspace = open_workspace(tmp_path, local_path=path)
    workspace.set_target("target", ("a", "b"))
    adjacent = path.with_suffix(".rowsetta.json") if path is not None else sidecar(tmp_path)
    adjacent.write_bytes(b"\xff\xfe")
    with pytest.raises(UserError) as caught:
        open_workspace(tmp_path, local_path=path)
    assert str(adjacent) in caught.value.what
    assert "UTF-8" in caught.value.next_step
    assert "rename" in caught.value.next_step.lower()
    assert adjacent.read_bytes() == b"\xff\xfe"
