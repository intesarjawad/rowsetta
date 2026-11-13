import argparse
import importlib
import json
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np
from pydantic import JsonValue, TypeAdapter

from rowsetta.core.features import teacher_frame
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import Table, load_csv
from rowsetta.core.teacher import predict_table
from rowsetta.teachers.tabicl import TabICLTeacher

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "src" / "rowsetta" / "datasets"
BENCH_JSON = ROOT / "docs" / "bench.json"
DATASET_TARGETS = {"penguins": "species", "bank": "y", "adult": "income"}
LABEL_COUNTS = (20, 50, 100, 200)
REPEATS = 5
SEED = 7
DRIFT_LABELS_PER_CLASS = 2


def dataset_session(name: str) -> tuple[Table, LabelStore]:
    """Load a bundled dataset with the same feature rules as product inference."""
    path = DATASETS / f"{name}.csv"
    data = path.read_bytes()
    table = load_csv(data)
    target = DATASET_TARGETS[name]
    store = LabelStore(
        classes=tuple(sorted(str(value) for value in table.frame[target].unique())),
        target=target,
        source=SourceRef.from_table(path.name, data, table),
    )
    return table, store


def penguins_protocol() -> tuple[Table, LabelStore]:
    """Draw two complete feature rows per species with one seed-7 generator."""
    table, store = dataset_session("penguins")
    complete = teacher_frame(table, store).frame.dropna().index
    rng = np.random.default_rng(SEED)
    for label in store.classes:
        candidates = table.frame.loc[complete]
        rows = candidates.index[candidates[store.target] == label].to_numpy()
        for row in rng.choice(rows, size=DRIFT_LABELS_PER_CLASS, replace=False):
            store.set_human(int(row), label)
    return table, store


def drift_accuracy(device: str | None = None) -> float:
    """Evaluate every remaining penguin, including rows with missing features."""
    table, store = penguins_protocol()
    proposals = predict_table(TabICLTeacher(device=device), table, store)
    rows = [row for row in store.source.row_ids() if row not in store.human]
    correct = sum(proposals.label[row] == table.frame.loc[row, store.target] for row in rows)
    return correct / len(rows)


def write_drift(accuracy: float, path: Path = BENCH_JSON) -> None:
    """Update the drift baseline without discarding other benchmark measurements."""
    document = (
        TypeAdapter(dict[str, JsonValue]).validate_json(path.read_text()) if path.exists() else {}
    )
    teacher = document.setdefault("teacher", {})
    if not isinstance(teacher, dict):
        message = "Benchmark teacher measurements must be a JSON object."
        raise TypeError(message)
    penguins = teacher.setdefault("penguins_6_labels", {})
    if not isinstance(penguins, dict):
        message = "Benchmark penguins measurements must be a JSON object."
        raise TypeError(message)
    penguins["accuracy"] = accuracy
    path.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")


def label_sample(table: Table, store: LabelStore, count: int) -> None:
    """Reserve two labels per class, then sample remaining training rows uniformly."""
    rng = np.random.default_rng(SEED)
    target = table.frame[store.target]
    for label in store.classes:
        candidates = target.index[target == label].to_numpy()
        for row in rng.choice(candidates, size=DRIFT_LABELS_PER_CLASS, replace=False):
            store.set_human(int(row), label)
    remaining = [row for row in store.source.row_ids() if row not in store.human]
    for row in rng.choice(remaining, size=count - len(store.human), replace=False):
        store.set_human(int(row), str(target.loc[row]))


def benchmark(devices: list[str], datasets: list[str]) -> None:
    """Time fit plus batched prediction after one untimed warm-up per cell."""
    for device in devices:
        if device == "mps" and not importlib.import_module("torch").backends.mps.is_available():
            message = "MPS is unavailable in this runtime. Rerun on a host with MPS access."
            raise SystemExit(message)
        for name in datasets:
            for count in LABEL_COUNTS:
                table, store = dataset_session(name)
                label_sample(table, store, count)
                teacher = TabICLTeacher(device=device)
                predict_table(teacher, table, store)
                seconds: list[float] = []
                for _ in range(REPEATS):
                    start = perf_counter()
                    predict_table(teacher, table, store)
                    seconds.append(perf_counter() - start)
                print(
                    f"{device} {name} rows={len(table.frame)} labels={count} "
                    f"median_seconds={median(seconds):.6f} runs={REPEATS}",
                    flush=True,
                )


def main() -> None:
    """Measure the teacher matrix or record the fixed penguins drift protocol."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drift", action="store_true")
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument("--device", choices=["cpu", "mps"], nargs="+")
    parser.add_argument("--dataset", choices=list(DATASET_TARGETS), nargs="+")
    args = parser.parse_args()
    if args.print_only and not args.drift:
        parser.error("--print requires --drift")
    if args.drift:
        if args.device and len(args.device) != 1:
            parser.error("--drift accepts at most one --device")
        accuracy = drift_accuracy(args.device[0] if args.device else None)
        if not args.print_only:
            write_drift(accuracy)
        print(f"teacher.penguins_6_labels.accuracy={accuracy:.9f}")
    else:
        benchmark(args.device or ["cpu", "mps"], args.dataset or list(DATASET_TARGETS))


if __name__ == "__main__":
    main()
