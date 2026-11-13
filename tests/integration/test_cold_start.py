import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from scripts import cold_start
from scripts.cold_start import COLD_BUDGET_SECONDS, Timing, drive, over_budget, wait_healthy

if TYPE_CHECKING:
    from pydantic import JsonValue

pytestmark = pytest.mark.native

LAUNCH_CODE = "cold-start-test-token"


def test_drive_labels_six_rows_and_waits_for_first_proposals(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "rowsetta", "demo", "--no-browser", "--port", str(port)],
        env={
            **os.environ,
            "ROWSETTA_TEACHER": "fake",
            "ROWSETTA_SESSION_TOKEN": LAUNCH_CODE,
            "HOME": str(tmp_path),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        started = perf_counter()
        wait_healthy(port, timeout=60)
        timing = drive(port, LAUNCH_CODE, started=started)
    finally:
        server.terminate()
        server.wait(timeout=30)
    assert 0 <= timing.health_seconds <= timing.first_proposals_seconds


@pytest.mark.parametrize(
    ("seconds", "warm", "over"),
    [
        (COLD_BUDGET_SECONDS, False, False),
        (COLD_BUDGET_SECONDS + 1, False, True),
        (COLD_BUDGET_SECONDS, True, True),
    ],
)
def test_budgets(seconds: float, *, warm: bool, over: bool) -> None:
    assert over_budget(Timing(health_seconds=1, first_proposals_seconds=seconds), warm=warm) == over


@pytest.mark.parametrize(
    ("timing", "over"),
    [
        (("cold", 10, 30), False),
        (("cold", 11, 20), True),
        (("warm", 1, 6), False),
        (("warm", 1, 7), True),
    ],
)
def test_browser_budgets_are_distinct_from_local_install_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timing: tuple[str, float, float],
    *,
    over: bool,
) -> None:
    visit, table_seconds, proposal_seconds = timing

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == cold_start.ROOT
        assert check
        Path(command[-1]).write_text(
            json.dumps(
                [
                    {
                        "requested_path": "lite",
                        "path": "lite",
                        "visit": visit,
                        "table_seconds": table_seconds,
                        "first_proposals_seconds": proposal_seconds,
                        "bytes": 42,
                    },
                    {
                        "requested_path": "lite",
                        "path": "lite",
                        "visit": "warm" if visit == "cold" else "cold",
                        "table_seconds": 1,
                        "first_proposals_seconds": 1,
                    },
                ]
            )
        )

    monkeypatch.setattr(
        cold_start, "subprocess", SimpleNamespace(run=run, check_output=subprocess.check_output)
    )
    monkeypatch.setattr(cold_start, "BENCH_JSON", tmp_path / "bench.json")
    monkeypatch.setattr(cold_start, "BROWSER_RUNS_JSON", tmp_path / "runs.json")
    if over:
        with pytest.raises(SystemExit, match="Browser"):
            cold_start.run_browser("http://127.0.0.1:4173/", no_budget=False, runs=1, path="lite")
    else:
        cold_start.run_browser("http://127.0.0.1:4173/", no_budget=False, runs=1, path="lite")


def test_browser_budget_uses_five_run_median() -> None:
    values: list[dict[str, JsonValue]] = [
        {
            "requested_path": "auto",
            "path": "tabiclv2",
            "visit": "warm",
            "table_seconds": 1,
            "first_proposals_seconds": seconds,
        }
        for seconds in (4, 5, 6, 7, 20)
    ]
    summaries = cold_start.browser_summaries(values)
    assert summaries == [
        {
            "requested_path": "auto",
            "path": "tabiclv2",
            "visit": "warm",
            "runs": 5,
            "table_seconds": 1,
            "first_proposals_seconds": 6,
        }
    ]


def test_browser_summaries_keep_requested_fallback_separate() -> None:
    values: list[dict[str, JsonValue]] = [
        {
            "requested_path": requested,
            "path": "lite",
            "visit": "cold",
            "table_seconds": 1,
            "first_proposals_seconds": seconds,
        }
        for requested, seconds in (("auto", 20), ("lite", 4))
    ]
    summaries = cold_start.browser_summaries(values)
    assert len(summaries) == 2
    assert [value["first_proposals_seconds"] for value in summaries] == [20, 4]


def test_browser_rejects_incomplete_pairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == cold_start.ROOT
        assert check
        Path(command[-1]).write_text(
            json.dumps(
                [
                    {
                        "requested_path": "auto",
                        "path": "tabiclv2",
                        "visit": "cold",
                        "table_seconds": 1,
                        "first_proposals_seconds": 20,
                    }
                ]
            )
        )

    monkeypatch.setattr(
        cold_start, "subprocess", SimpleNamespace(run=run, check_output=subprocess.check_output)
    )
    monkeypatch.setattr(cold_start, "BENCH_JSON", tmp_path / "bench.json")
    with pytest.raises(SystemExit, match="5 complete cold/warm pairs"):
        cold_start.run_browser("http://127.0.0.1:4173/", no_budget=True)
    assert not (tmp_path / "bench.json").exists()
