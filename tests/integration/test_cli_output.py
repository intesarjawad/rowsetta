import os
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

pytestmark = pytest.mark.native

GOLDENS = Path(__file__).parents[1] / "golden" / "cli"
DEMO_PORT = "8799"
STARTUP_LINES = 3
STARTUP_TIMEOUT_SECONDS = 30


def environment(tmp_path: Path, *, teacher: str = "fake") -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "COLUMNS": "80",
        "ROWSETTA_TEACHER": teacher,
        "ROWSETTA_DEVICE": "cpu",
        "HOME": str(tmp_path),
        "HF_HOME": str(tmp_path / "hf"),
    }


def transcript(command: str, stdout: str, stderr: str, returncode: int | None) -> str:
    # Native libraries may warn on stderr at import; only the error contract is ours.
    contract = "".join(
        line for line in stderr.splitlines(keepends=True) if line.startswith(("error: ", "Next: "))
    )
    text = f"$ rowsetta {command}\n{stdout}{contract}"
    if returncode is not None:
        text += f"[exit {returncode}]\n"
    for package in ("torch", "tabicl"):
        text = re.sub(
            rf"^({package} +){re.escape(version(package))}$",
            r"\1<version>",
            text,
            flags=re.MULTILINE,
        )
    return re.sub(r"token=\S+", "token=<token>", text)


def run(tmp_path: Path, command: str, *, teacher: str = "fake") -> str:
    result = subprocess.run(
        [sys.executable, "-m", "rowsetta", *command.split()],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=environment(tmp_path, teacher=teacher),
    )
    return transcript(command, result.stdout, result.stderr, result.returncode)


def assert_golden(name: str, text: str) -> None:
    path = GOLDENS / f"{name}.txt"
    if os.environ.get("ROWSETTA_UPDATE_CLI_GOLDENS") == "1":
        GOLDENS.mkdir(exist_ok=True)
        path.write_text(text)
    assert path.read_text() == text, "Regenerate CLI fixtures with make golden."


def test_help(tmp_path: Path) -> None:
    assert_golden("help", run(tmp_path, "--help"))


def test_doctor_without_a_cached_model(tmp_path: Path) -> None:
    assert_golden("doctor", run(tmp_path, "doctor"))


def test_offline_first_run(tmp_path: Path) -> None:
    transcript = run(tmp_path, "demo --offline --no-browser", teacher="tabicl")

    assert_golden("error-offline-first-run", transcript)


def test_too_many_columns(tmp_path: Path) -> None:
    names = [f"c{index}" for index in range(101)]
    (tmp_path / "wide.csv").write_text(",".join(names) + "\n" + ",".join("1" for _ in names) + "\n")

    assert_golden("error-too-many-columns", run(tmp_path, "open wide.csv --no-browser"))


def test_missing_session(tmp_path: Path) -> None:
    assert_golden("error-missing-session", run(tmp_path, "export absent.rowsetta.json"))


def test_demo_startup_lines(tmp_path: Path) -> None:
    command = f"demo penguins --no-browser --port {DEMO_PORT}"
    with subprocess.Popen(
        [sys.executable, "-m", "rowsetta", *command.split()],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=tmp_path,
        env=environment(tmp_path),
    ) as server:
        assert server.stdout is not None
        try:
            lines = [server.stdout.readline() for _ in range(STARTUP_LINES)]
        finally:
            server.terminate()
            server.wait(timeout=STARTUP_TIMEOUT_SECONDS)

    assert_golden("demo", transcript(command, "".join(lines), "", None))
