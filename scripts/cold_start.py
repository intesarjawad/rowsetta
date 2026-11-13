import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.cookiejar import CookieJar
from statistics import median
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import pandas as pd
from pydantic import JsonValue, TypeAdapter

from scripts.bench_common import BENCH_JSON, DOCUMENT, JSON, ROOT, atomic_json, provenance

# Time to first proposals on the bundled penguins, from a cold or a warm cache.
COLD_BUDGET_SECONDS = 180
WARM_BUDGET_SECONDS = 15
# The browser demo has its own, tighter budgets: no install step hides its startup.
BROWSER_TABLE_BUDGET_SECONDS = 10
BROWSER_COLD_BUDGET_SECONDS = 30
BROWSER_WARM_BUDGET_SECONDS = 6
PORT = 8787
POLL_SECONDS = 0.2
BROWSER_RUNS_JSON = ROOT / "docs/bench-data/browser-startup-runs.json"
PENGUINS = ROOT / "src/rowsetta/datasets/penguins.csv"
LABELS_PER_SPECIES = 2  # The fewest that start proposals.


@dataclass(frozen=True)
class Timing:
    """Seconds from launch to each milestone."""

    health_seconds: float
    first_proposals_seconds: float


def over_budget(timing: Timing, *, warm: bool) -> bool:
    """Compare first proposals with the cold or warm budget."""
    budget = WARM_BUDGET_SECONDS if warm else COLD_BUDGET_SECONDS
    return timing.first_proposals_seconds > budget


def wait_healthy(port: int, *, timeout: float) -> float:
    """Poll /health without a proxy until it answers; return the seconds waited."""
    opener = build_opener(ProxyHandler({}))
    start = perf_counter()
    while perf_counter() - start < timeout:
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                if json.load(response).get("ok") is True:
                    return perf_counter() - start
        except (URLError, ConnectionError):
            sleep(POLL_SECONDS)
    message = f"Port {port} /health did not answer within {timeout:.0f} s"
    raise TimeoutError(message)


def drive(port: int, token: str, *, started: float) -> Timing:
    """Label six penguins through the API and wait for the refit that answers them."""
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def call(method: str, path: str, body: object | None = None) -> dict[str, object]:
        data = None if body is None else json.dumps(body).encode()
        request = Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
        request.add_header("Content-Type", "application/json")
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    health = perf_counter() - started
    try:
        opener.open(f"http://127.0.0.1:{port}/?token={token}", timeout=30).close()
    except HTTPError as error:
        # The redirect target is the page, absent from a source install without a build.
        if error.code != HTTPStatus.SERVICE_UNAVAILABLE:
            raise
    species = pd.read_csv(PENGUINS)["species"]
    call("POST", "/target", {"target": "species", "classes": sorted(species.unique())})
    for label, rows in species.groupby(species).groups.items():
        for row in rows[:LABELS_PER_SPECIES]:
            call("PUT", f"/labels/{row}", {"label": label, "mode": "human"})
    while True:
        state = call("GET", "/state")
        if state["failure"] is not None:
            message = f"Refit failed: {state['failure']}"
            raise RuntimeError(message)
        if state["refit_generation"] == state["generation"] and state["proposals"]:
            return Timing(health, perf_counter() - started)
        sleep(POLL_SECONDS)


def du_bytes(*folders: Path) -> int:
    """Count bytes the install wrote, the download size on a clean cache."""
    return sum(
        path.stat().st_size for folder in folders for path in folder.rglob("*") if path.is_file()
    )


def run_local(spec: str, caches: Path) -> Timing:
    """Start `uvx SPEC demo` on the given caches and time it to first proposals."""
    token = secrets.token_urlsafe(16)
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(caches / "uv"),
        "UV_TOOL_DIR": str(caches / "tools"),
        "HF_HOME": str(caches / "hf"),
        "ROWSETTA_SESSION_TOKEN": token,
    }
    backend: list[str] = ["--torch-backend", "cpu"] if sys.platform == "linux" else []
    command = ["uvx", *backend, spec, "demo", "--no-browser", "--port", str(PORT)]
    started = perf_counter()
    server = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL)  # noqa: S603
    try:
        wait_healthy(PORT, timeout=COLD_BUDGET_SECONDS * 2)
        return drive(PORT, token, started=started)
    finally:
        server.terminate()
        server.wait(timeout=30)


def main() -> None:
    """Measure cold and warm local time to demo and record it in docs/bench.json."""
    cli = argparse.ArgumentParser(description="Time from a clean install to first proposals")
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local", metavar="SPEC", help="for example rowsetta@0.1.0")
    mode.add_argument("--browser", metavar="URL", help="built static demo URL")
    cli.add_argument("--no-budget", action="store_true", help="measure without asserting budgets")
    cli.add_argument("--browser-runs", type=int, default=5, help="clean profiles per path")
    cli.add_argument("--browser-path", choices=("both", "auto", "lite"), default="both")
    args = cli.parse_args()
    if args.browser:
        run_browser(
            args.browser, no_budget=args.no_budget, runs=args.browser_runs, path=args.browser_path
        )
        return
    with tempfile.TemporaryDirectory(prefix="rowsetta-cold-") as folder:
        caches = Path(folder)
        cold = run_local(args.local, caches)
        downloaded = du_bytes(caches / "uv", caches / "tools", caches / "hf")
        warm = run_local(args.local, caches)
    section = provenance(
        "scripts/cold_start.py",
        cold.first_proposals_seconds + warm.first_proposals_seconds,
        {
            "spec": args.local,
            "date": datetime.now(UTC).date().isoformat(),
            "machine": platform.node(),
        },
    )
    section.results = [
        {"visit": "cold", **asdict(cold), "bytes": downloaded},
        {"visit": "warm", **asdict(warm)},
    ]
    document = DOCUMENT.validate_json(BENCH_JSON.read_text()) if BENCH_JSON.exists() else {}
    existing = document.get("cold_start")
    cold_start = existing if isinstance(existing, dict) else {}
    cold_start["local"] = JSON.validate_python(section.model_dump(mode="json"))
    document["cold_start"] = cold_start
    atomic_json(BENCH_JSON, document)
    print(f"cold_start local cold={cold} warm={warm} bytes={downloaded}", flush=True)
    if not args.no_budget and (over_budget(cold, warm=False) or over_budget(warm, warm=True)):
        sys.exit(f"Over budget: cold {COLD_BUDGET_SECONDS} s, warm {WARM_BUDGET_SECONDS} s")


def browser_summaries(values: list[dict[str, JsonValue]]) -> list[dict[str, JsonValue]]:
    """Report each teacher and visit separately; budgets apply to the medians."""
    summaries: list[dict[str, JsonValue]] = []
    paths = sorted({(str(value["requested_path"]), str(value["path"])) for value in values})
    for requested_path, path in paths:
        for visit in ("cold", "warm"):
            group = [
                value
                for value in values
                if value["requested_path"] == requested_path
                and value["path"] == path
                and value["visit"] == visit
            ]
            if not group:
                continue
            summary: dict[str, JsonValue] = {
                "requested_path": requested_path,
                "path": path,
                "visit": visit,
                "runs": len(group),
            }
            for metric in ("table_seconds", "first_proposals_seconds"):
                numbers = [value[metric] for value in group]
                numeric = [value for value in numbers if isinstance(value, (int, float))]
                if len(numeric) != len(numbers):
                    msg = f"Invalid browser metric: {metric}"
                    raise TypeError(msg)
                summary[metric] = median(numeric)
            summaries.append(summary)
    return summaries


def run_browser(url: str, *, no_budget: bool, runs: int = 5, path: str = "both") -> None:
    """Measure real browser milestones and transferred bytes in a clean profile."""
    started = perf_counter()
    with tempfile.TemporaryDirectory(prefix="rowsetta-browser-result-") as folder:
        result = Path(folder) / "timings.json"
        command = [
            shutil.which("node") or "node",
            "scripts/browser_cold_start.mjs",
            "--runs",
            str(runs),
            "--path",
            path,
            url,
            str(result),
        ]
        subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603 -- Fixed local harness.
        values = JSON.validate_json(result.read_text())
    section = provenance(
        "scripts/cold_start.py",
        perf_counter() - started,
        {
            "url": url,
            "runs_per_path": runs,
            "requested_path": path,
            "max_one_minute_load": 8,
            "download_mbit_s": 50,
            "latency_ms": 40,
            "dirty_tree": bool(
                subprocess.check_output(  # noqa: S603 -- Fixed local command.
                    [shutil.which("git") or "git", "status", "--porcelain"], cwd=ROOT, text=True
                ).strip()
            ),
            "browser_harness_sha256": hashlib.sha256(
                (ROOT / "scripts/browser_cold_start.mjs").read_bytes()
            ).hexdigest(),
        },
    )
    measurements = TypeAdapter(list[dict[str, JsonValue]]).validate_python(values)
    summaries = browser_summaries(measurements)
    requested_paths = {"auto", "lite"} if path == "both" else {path}
    reported_paths = {
        name for value in summaries if isinstance(name := value["requested_path"], str)
    }
    if (
        reported_paths != requested_paths
        or len(summaries) != 2 * len(requested_paths)
        or any(value["runs"] != runs for value in summaries)
    ):
        sys.exit(f"Browser timing requires {runs} complete cold/warm pairs per requested path")
    section.results = summaries
    atomic_json(BROWSER_RUNS_JSON, {"runs": measurements})
    document = DOCUMENT.validate_json(BENCH_JSON.read_text()) if BENCH_JSON.exists() else {}
    existing = document.get("cold_start")
    cold_start = existing if isinstance(existing, dict) else {}
    cold_start["browser"] = JSON.validate_python(section.model_dump(mode="json"))
    document["cold_start"] = cold_start
    atomic_json(BENCH_JSON, document)
    print(json.dumps(summaries, indent=2), flush=True)
    if not no_budget:
        for value in summaries:
            seconds = value.get("first_proposals_seconds")
            table_seconds = value.get("table_seconds")
            budget = (
                BROWSER_COLD_BUDGET_SECONDS
                if value.get("visit") == "cold"
                else BROWSER_WARM_BUDGET_SECONDS
            )
            if (
                isinstance(table_seconds, (int, float))
                and table_seconds > BROWSER_TABLE_BUDGET_SECONDS
            ):
                sys.exit(f"Browser table over budget: {table_seconds:.3f} s")
            if isinstance(seconds, (int, float)) and seconds > budget:
                sys.exit(f"Browser visit over budget: {seconds:.3f} > {budget} s")


if __name__ == "__main__":
    main()
