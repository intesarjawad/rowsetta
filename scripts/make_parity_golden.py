"""Write fixed training inputs and native TabICLv2 probabilities for the spike."""

import argparse
import importlib
import json
from pathlib import Path

import numpy as np
from parity_tensors import ParityClassifier, tensor_trace

from rowsetta.core.features import teacher_frame
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import load_csv
from rowsetta.teachers.checkpoint import checkpoint_path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Generate golden data with the shared feature frame and fixed seed."""
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--estimators", type=int, default=4)
    cli.add_argument("--output", type=Path, default=ROOT / "frontend/public/spike/golden.json")
    cli.add_argument(
        "--trace", action="store_true", help="write native tensor boundaries beside the golden"
    )
    args = cli.parse_args()
    traces: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    for name, target, count in (
        ("penguins", "species", 20),
        ("bank_2k", "y", 50),
        ("adult_2k", "income", 50),
    ):
        data = (ROOT / f"src/rowsetta/datasets/{name}.csv").read_bytes()
        table = load_csv(data, max_rows=2000)
        y = table.frame[target].astype(str)
        classes = tuple(sorted(y.unique()))
        store = LabelStore(
            target=target, classes=classes, source=SourceRef.from_table(f"{name}.csv", data, table)
        )
        x = teacher_frame(table, store).frame
        rng = np.random.default_rng(7)
        chosen: list[int] = []
        for label in classes:
            available = y.index[(y == label) & x.notna().all(axis=1)].to_numpy()
            chosen.extend(
                int(row) for row in rng.choice(available, count // len(classes), replace=False)
            )
        remaining = count - len(chosen)
        if remaining:
            chosen.extend(
                int(row)
                for row in rng.choice(
                    y.index.difference(chosen).to_numpy(dtype=np.int64), remaining, replace=False
                )
            )
        model: ParityClassifier = importlib.import_module("tabicl").TabICLClassifier(
            n_estimators=args.estimators,
            kv_cache=True,
            device="cpu",
            model_path=checkpoint_path(),
            allow_auto_download=False,
            random_state=7,
            verbose=False,
        )
        model.fit(x.loc[chosen], y.loc[chosen])
        probabilities = np.asarray(model.predict_proba(x))
        if args.trace:
            traces.append({"name": name, "traces": tensor_trace(model, x.loc[chosen], x)})
        # JSON null is the browser API's missing value; use pandas' JSON conversion.
        rows = json.loads(x.to_json(orient="values"))
        results.append(
            {
                "name": name,
                "train": [rows[i] for i in chosen],
                "labels": y.loc[chosen].tolist(),
                "test": rows,
                "classes": model.classes_.tolist(),
                "probabilities": probabilities.tolist(),
            }
        )
        print(f"{name}: {len(chosen)} labels, {len(x)} rows", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.trace:
        args.output.with_name("native-tensors.json").write_text(json.dumps(traces))
    args.output.write_text(json.dumps({"estimators": args.estimators, "datasets": results}))


if __name__ == "__main__":
    main()
