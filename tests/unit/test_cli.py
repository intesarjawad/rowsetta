import json
import os
import shlex
import socket
import subprocess
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

import pytest
import uvicorn

from rowsetta import cli

pytestmark = pytest.mark.native

ROOT = Path(__file__).resolve().parents[2]
SESSION = Path("tests/fixtures/penguins.rowsetta.json")
DATASET = ROOT / "src/rowsetta/datasets/penguins.csv"


def run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "ROWSETTA_TEACHER": "fake", "NO_COLOR": "1"}
    return subprocess.run(
        [sys.executable, "-m", "rowsetta", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=environment,
    )


def assert_user_error(
    result: subprocess.CompletedProcess[str], *, what: str, next_step: str
) -> None:
    assert result.returncode == 1
    assert result.stdout == ""
    error, recovery = result.stderr.splitlines()
    assert error.startswith("error: ")
    assert what in error
    assert recovery.startswith("Next: rowsetta ")
    assert next_step in recovery


def test_help_requires_no_credentials() -> None:
    environment = {key: value for key, value in os.environ.items() if key != "HF_TOKEN"}
    result = subprocess.run(
        [sys.executable, "-m", "rowsetta", "--help"],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )

    assert "usage: rowsetta" in result.stdout
    assert "Rowsetta" in result.stdout
    assert result.stderr == ""


def test_help_lists_the_four_commands() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "{open,demo,export,doctor}" in result.stdout


def test_unknown_option_fails_with_usage() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "rowsetta", "--unknown"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "unrecognized arguments: --unknown" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("open", "data.csv", "--max-file-mb", "0"),
        ("open", "data.csv", "--max-file-mb", "-3"),
        ("open", "data.csv", "--columns", ""),
        ("open", "data.csv", "--columns", "species,,island"),
        ("demo", "iris"),
        ("export", str(SESSION), "--format", "csv"),
        ("export", str(SESSION), "--dialect", "mysql"),
    ],
)
def test_invalid_options_are_usage_errors(args: tuple[str, ...]) -> None:
    result = run_cli(*args)

    assert result.returncode == 2
    assert "usage: rowsetta" in result.stderr


@pytest.mark.parametrize("port", ["0", "-1", "65536", "not-a-port"])
@pytest.mark.parametrize("command", [("demo",), ("open", "data.csv")])
def test_invalid_ports_fail_during_argument_parsing(port: str, command: tuple[str, ...]) -> None:
    result = run_cli(*command, "--port", port)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.splitlines()[-1].endswith(
        "argument --port: must be an integer in 1..65535"
    )
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("port", ["1", "65535"])
def test_port_bounds_are_accepted(port: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["rowsetta", "demo", "--port", port])
    seen: list[int] = []

    def serve(_parser: ArgumentParser, args: Namespace) -> None:
        seen.append(args.port)

    monkeypatch.setattr(cli, "_serve", serve)
    cli.main()
    assert seen == [int(port)]


def test_export_writes_verified_sql_for_the_saved_session() -> None:
    result = run_cli("export", str(SESSION), "--format", "sql", "--dialect", "duckdb")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("-- ")
    assert "344/344 rows identical" in result.stdout
    assert 'AS "predicted_species"' in result.stdout


@pytest.mark.parametrize(
    ("export_format", "marker"),
    [("python", "def predict("), ("json", '"identical": 344'), ("dbt", "models/species_rule.sql")],
)
def test_export_writes_every_format(export_format: str, marker: str) -> None:
    result = run_cli("export", str(SESSION), "--format", export_format, "--dialect", "duckdb")

    assert result.returncode == 0, result.stderr
    assert marker in result.stdout


def test_dbt_export_is_a_json_map_of_project_files() -> None:
    result = run_cli("export", str(SESSION), "--format", "dbt", "--dialect", "sqlite")

    files = json.loads(result.stdout)
    assert set(files) == {
        "models/species_rule.sql",
        "models/schema.yml",
        "tests/species_rule_coverage.sql",
    }
    assert "344/344 rows identical" in files["models/species_rule.sql"]


def write_session(directory: Path, source: bytes) -> Path:
    (directory / "penguins.csv").write_bytes(source)
    session = json.loads((ROOT / SESSION).read_text())
    session["source"]["file_name"] = "penguins.csv"
    path = directory / "penguins.rowsetta.json"
    path.write_text(json.dumps(session))
    return path


def test_export_resolves_the_csv_beside_the_session(tmp_path: Path) -> None:
    session = write_session(tmp_path, DATASET.read_bytes())

    result = run_cli("export", session.name, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "344/344 rows identical" in result.stdout


def test_export_rejects_a_changed_csv(tmp_path: Path) -> None:
    session = write_session(tmp_path, DATASET.read_bytes().replace(b"Torgersen", b"Torgersem", 1))

    assert_user_error(
        run_cli("export", str(session)),
        what="changed since",
        next_step=f"open {shlex.quote(str(tmp_path / 'penguins.csv'))}",
    )


def test_export_names_a_missing_csv(tmp_path: Path) -> None:
    session = write_session(tmp_path, b"")
    (tmp_path / "penguins.csv").unlink()

    assert_user_error(
        run_cli("export", str(session)),
        what=str(tmp_path / "penguins.csv"),
        next_step="export",
    )


def test_export_rejects_an_invalid_session(tmp_path: Path) -> None:
    session = tmp_path / "broken.rowsetta.json"
    session.write_text('{"human": {}}')

    assert_user_error(
        run_cli("export", str(session)), what="broken.rowsetta.json", next_step="open"
    )


def test_export_rejects_a_non_utf8_session(tmp_path: Path) -> None:
    session = tmp_path / "broken.rowsetta.json"
    session.write_bytes(b"\xff\xfeinvalid")
    assert_user_error(run_cli("export", str(session)), what="not a saved session", next_step="open")


def test_invalid_host_has_recovery_without_an_alternative_port() -> None:
    result = run_cli("demo", "--host", "invalid.invalid", "--no-browser")
    assert_user_error(result, what="Could not bind invalid.invalid", next_step="--host 127.0.0.1")
    assert "--port" not in result.stderr


def test_export_names_a_missing_session(tmp_path: Path) -> None:
    assert_user_error(
        run_cli("export", "absent.rowsetta.json", cwd=tmp_path),
        what="absent.rowsetta.json",
        next_step="export",
    )


def test_open_rejects_a_file_over_the_raised_limit_before_reading_it(tmp_path: Path) -> None:
    large = tmp_path / "large.csv"
    large.write_bytes(b"x\n" + b"1\n" * 500_001)

    assert_user_error(
        run_cli("open", "large.csv", "--max-file-mb", "1", "--no-browser", cwd=tmp_path),
        what="the limit is 1 MB",
        next_step="open large.csv --max-file-mb 2",
    )


def test_open_names_a_missing_file(tmp_path: Path) -> None:
    assert_user_error(
        run_cli("open", "absent.csv", "--no-browser", cwd=tmp_path),
        what="absent.csv",
        next_step="open",
    )


def test_open_rejects_unknown_columns_with_a_runnable_selection(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("species,island\nAdelie,Dream\n")

    assert_user_error(
        run_cli("open", "data.csv", "--columns", "species,isle", "--no-browser", cwd=tmp_path),
        what="`isle`",
        next_step="open data.csv --columns species,island",
    )


@pytest.mark.parametrize("port_style", ["separate", "equals"])
def test_busy_port_does_not_open_the_browser_and_prints_a_retry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], port_style: str
) -> None:
    opened: list[str] = []
    monkeypatch.setenv("ROWSETTA_TEACHER", "fake")
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    with socket.create_server(("127.0.0.1", 0)) as occupied:
        port = occupied.getsockname()[1]
        options = ["--port", str(port)] if port_style == "separate" else [f"--port={port}"]
        monkeypatch.setattr(sys, "argv", ["rowsetta", "demo", "penguins", *options])
        with pytest.raises(SystemExit, match="1"):
            cli.main()
    output = capsys.readouterr()
    assert output.out == ""
    assert opened == []
    assert "Could not bind" in output.err
    assert "Next: rowsetta demo penguins --port " in output.err
    assert str(port) not in output.err.split("Next: ")[1]


def test_browser_opens_only_after_the_port_is_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.create_server(("127.0.0.1", 0)) as available:
        port = available.getsockname()[1]
    opened: list[str] = []

    def open_browser(url: str) -> bool:
        with (
            socket.socket() as probe,
            pytest.raises(OSError, match=r"Address already in use|WinError 10048"),
        ):
            probe.bind(("127.0.0.1", port))
        opened.append(url)
        return True

    monkeypatch.setenv("ROWSETTA_TEACHER", "fake")
    monkeypatch.setattr(sys, "argv", ["rowsetta", "demo", "--port", str(port)])
    monkeypatch.setattr(cli.webbrowser, "open", open_browser)

    def serve(_server: uvicorn.Server, **_options: object) -> None:
        return

    monkeypatch.setattr(uvicorn.Server, "run", serve)
    cli.main()
    assert len(opened) == 1


def test_dbt_invalid_target_is_actionable_before_refitting(tmp_path: Path) -> None:
    session = write_session(tmp_path, DATASET.read_bytes())
    saved = json.loads(session.read_text())
    saved["target"] = "Risk category"
    session.write_text(json.dumps(saved))
    result = run_cli("export", str(session), "--format", "dbt")
    assert result.returncode == 1
    assert "dbt identifier" in result.stderr
    assert "SQL, Python or JSON" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_ctrl_c_stops_without_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(_server: uvicorn.Server, **_options: object) -> None:
        raise KeyboardInterrupt

    with socket.create_server(("127.0.0.1", 0)) as available:
        port = available.getsockname()[1]
    monkeypatch.setenv("ROWSETTA_TEACHER", "fake")
    monkeypatch.setattr(sys, "argv", ["rowsetta", "demo", "--no-browser", "--port", str(port)])
    monkeypatch.setattr(uvicorn.Server, "run", interrupt)
    cli.main()
