import os
import subprocess
import sys
from time import perf_counter
from urllib.request import ProxyHandler, build_opener

from scripts.bench_common import ROOT, parser
from scripts.bench_learners import LEARNERS
from scripts.bench_llm import verify_model


def execute(module: str, arguments: list[str]) -> None:
    """Use a fresh process per phase so model memory is released between phases."""
    os.chdir(ROOT)
    code = subprocess.run(  # noqa: S603 -- Fixed local benchmark entrypoint.
        [sys.executable, "-m", f"scripts.{module}", *arguments], check=False
    ).returncode
    if code:
        raise SystemExit(code)


def main() -> None:
    """Run serial phases unattended; repeat the same command to resume saved cells."""
    cli = parser("Full resumable benchmark; LLM runs last in its own process")
    cli.add_argument("--only", choices=LEARNERS)
    args = cli.parse_args()
    if not args.only and args.budgets and set(args.budgets) != {50}:
        cli.error(
            "A combined run accepts budget 50 or the default full matrix; "
            "use a phase script for other budgets"
        )
    arguments: list[str] = []
    if args.smoke:
        arguments.append("--smoke")
    for option in ("datasets", "budgets", "seeds"):
        values = getattr(args, option)
        if values:
            arguments.extend([f"--{option}", *(str(value) for value in values)])
    if args.only:
        execute("bench_active", [*arguments, "--only", args.only])
        execute("render_bench", [])
        return
    verify_model(build_opener(ProxyHandler({})))
    start = perf_counter()
    if not args.smoke:
        execute("fetch_bench_datasets", ["--verify"])
    execute("bench_active", arguments)
    execute("bench_active", [*arguments, "--oracle-noise", "0.1"])
    execute("bench_distill", arguments)
    execute("bench_leaks", arguments)
    execute("bench_llm", arguments)
    execute("render_bench", [])
    print(f"benchmark complete wall_seconds={perf_counter() - start:.3f}", flush=True)


if __name__ == "__main__":
    main()
