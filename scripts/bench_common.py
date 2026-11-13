import argparse
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import platform
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
from pydantic import BaseModel, JsonValue, TypeAdapter

from rowsetta.core.distill import Count, Rate
from rowsetta.core.prereg import DATASETS, SEEDS
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import Table, load_csv
from scripts.fetch_bench_datasets import DATASETS as ARCHIVES
from scripts.fetch_bench_datasets import verify_archive

ROOT = Path(__file__).resolve().parents[1]
BENCH_JSON = ROOT / "docs/bench.json"
BUDGETS = (10, 20, 50, 100, 200)
TARGETS: dict[str, str] = dict(
    zip(DATASETS, ("species", "y", "income", "Class", "class", "class"), strict=True)
)
DEFAULT_THRESHOLD = 0.60
BOOTSTRAP_DRAWS = 2_000
JSON = TypeAdapter(JsonValue)
DOCUMENT = TypeAdapter(dict[str, JsonValue])


class Observation(BaseModel):
    """A completed acquisition checkpoint, reusable by every downstream comparison."""

    dataset: str
    source_sha256: str
    budget: int
    seed: int
    learner: str
    strategy: str
    noise: float
    human: dict[int, str]
    eval_rows: list[int]
    classes: tuple[str, ...]
    proba: list[list[float]]
    wall_seconds: float
    metrics: dict[str, JsonValue]


class Section(BaseModel):
    """Common provenance for independently resumable benchmark sections."""

    script: str
    git_sha: str
    machine: str
    wall_seconds: float
    settings: dict[str, JsonValue]
    results: list[dict[str, JsonValue]]


def cache_root() -> Path:
    """Honor XDG_CACHE_HOME so restricted runs can use a writable location."""
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "rowsetta/bench"


def atomic_json(path: Path, value: object) -> None:
    """Keep the previous complete result if the process is interrupted during a write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def fingerprint() -> str:
    """Invalidate checkpoints when numerical code or dependency versions change."""
    digest = hashlib.sha256((ROOT / "uv.lock").read_bytes())
    for folder in (
        ROOT / "scripts",
        ROOT / "src/rowsetta/core",
        ROOT / "src/rowsetta/teachers",
    ):
        for path in sorted(folder.rglob("*.py")):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def checkpoint_path(section: str, settings: dict[str, JsonValue]) -> Path:
    """Key caches by full settings and source content, never by a display label alone."""
    signature = {
        "code": fingerprint(),
        "settings": settings,
        "device": os.environ.get("ROWSETTA_DEVICE", "auto"),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    return cache_root() / section / f"{key}.json"


def load_checkpoint[T: BaseModel](path: Path, model: type[T]) -> T | None:
    """Reject malformed cached measurements instead of silently reusing them."""
    return model.model_validate_json(path.read_text()) if path.exists() else None


def publish(name: str, section: Section, **extra: JsonValue) -> None:
    """Replace one section while preserving measurements from the other scripts."""
    document = DOCUMENT.validate_json(BENCH_JSON.read_text()) if BENCH_JSON.exists() else {}
    document[name] = JSON.validate_python({**section.model_dump(mode="json"), **extra})
    atomic_json(BENCH_JSON, document)


def provenance(script: str, seconds: float, settings: Mapping[str, object]) -> Section:
    """Record executable, revision, runtime and settings alongside measurements."""
    revision = subprocess.check_output(  # noqa: S603 -- Fixed local command.
        [shutil.which("git") or "git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    return Section(
        script=script,
        git_sha=revision,
        machine=f"{platform.system()} {platform.machine()} Python {platform.python_version()}",
        wall_seconds=seconds,
        settings={
            **DOCUMENT.validate_python(settings),
            "source_sha256": fingerprint(),
            "device": os.environ.get("ROWSETTA_DEVICE", "auto"),
            "numpy": importlib.metadata.version("numpy"),
            "scikit_learn": importlib.metadata.version("scikit-learn"),
        },
        results=[],
    )


def parser(description: str, *, budgets: tuple[int, ...] = BUDGETS) -> argparse.ArgumentParser:
    """Share explicit matrix controls across the unattended and smoke commands."""
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--smoke", action="store_true")
    result.add_argument("--datasets", choices=DATASETS, nargs="+")
    result.add_argument("--budgets", type=int, choices=budgets, nargs="+")
    result.add_argument("--seeds", type=int, nargs="+")
    return result


def matrix(args: argparse.Namespace) -> tuple[list[str], list[int], list[int]]:
    """Keep the smoke to one dataset, one budget and two seeds."""
    return (
        args.datasets or (["penguins"] if args.smoke else list(DATASETS)),
        sorted(set(args.budgets or ([50] if args.smoke else list(BUDGETS)))),
        args.seeds or (list(SEEDS[:2]) if args.smoke else list(SEEDS)),
    )


def dataset(name: str) -> tuple[Table, SourceRef]:
    """Load pinned public fixtures; UCI archives must first pass their checksum."""
    if name in ("penguins", "bank", "adult"):
        data = (ROOT / "src/rowsetta/datasets" / f"{name}.csv").read_bytes()
    else:
        archive = next(item for item in ARCHIVES if item.name == name)
        path = cache_root() / f"{name}.zip"
        if not path.exists():
            message = (
                "Fetch benchmark archives first: uv run python scripts/fetch_bench_datasets.py"
            )
            raise FileNotFoundError(message)
        raw = path.read_bytes()
        verify_archive(raw, archive)
        with ZipFile(io.BytesIO(raw)) as zipped:
            if name == "dry_bean":
                member = next(item for item in zipped.namelist() if item.lower().endswith(".arff"))
                records, _ = importlib.import_module("scipy.io.arff").loadarff(
                    io.StringIO(zipped.read(member).decode())
                )
                frame = pd.DataFrame(records)
                frame["Class"] = frame["Class"].str.decode("utf-8")
            else:
                member = next(item for item in zipped.namelist() if item.endswith(".data"))
                frame = pd.read_csv(io.BytesIO(zipped.read(member)), header=None, na_values="?")
                columns = [f"feature_{i}" for i in range(frame.shape[1])]
                columns[0 if name == "mushroom" else -1] = "class"
                frame.columns = columns
        data = frame.to_csv(index=False).encode()
    table = load_csv(data)
    return table, SourceRef.from_table(f"{name}.csv", data, table)


def session(name: str, seed: int) -> tuple[Table, LabelStore]:
    """Draw the random evaluation sample before the two-per-class seed set."""
    table, source = dataset(name)
    target = TARGETS[name]
    classes = tuple(sorted(str(value) for value in table.frame[target].unique()))
    rng = np.random.default_rng(seed)
    rows = [int(row) for row in rng.permutation(table.frame.index)]
    heldout = rows[: min(500, int(0.30 * len(rows)))]
    remaining = table.frame.drop(index=heldout)
    human: dict[int, str] = {}
    for label in classes:
        candidates = remaining.index[remaining[target].astype(str) == label]
        for row in rng.choice(candidates, 2, replace=False):
            human[int(row)] = label
    return table, LabelStore(
        classes=classes,
        target=target,
        source=source,
        threshold=DEFAULT_THRESHOLD,
        human=human,
        eval={row: str(table.frame.loc[row, target]) for row in heldout},
        eval_served=heldout,
        eval_seed=seed,
    )


def band(values: list[float]) -> dict[str, JsonValue]:
    """Use seed-7 percentile bootstrap bands over independent seed measurements."""
    samples = np.random.default_rng(7).choice(values, size=(BOOTSTRAP_DRAWS, len(values)))
    lo, hi = np.quantile(samples.mean(axis=1), [0.025, 0.975])
    return {"mean": float(np.mean(values)), "lo": float(lo), "hi": float(hi)}


def count_json(value: Count | Rate) -> JsonValue:
    """Convert metric dataclasses to finite JSON at the reporting boundary."""
    return JSON.validate_python(asdict(value))
