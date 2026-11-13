"""Summarize native/browser tensors; optionally compare ONNX CPU and WebGPU.

The --graph comparison needs uv run --with onnxruntime==1.31.1.
"""

import argparse
import importlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1] / "frontend/public/spike"


def difference(expected: object, actual: object) -> dict[str, object]:
    """Retain a maximum-error coordinate and values, not just a pass/fail flag."""
    left = np.asarray(expected, dtype=np.float64)
    right = np.asarray(actual, dtype=np.float64)
    if left.shape != right.shape:
        message = f"Tensor shapes differ: {left.shape} vs {right.shape}"
        raise ValueError(message)
    delta = np.abs(left - right)
    index = np.unravel_index(delta.argmax(), delta.shape)
    return {
        "shape": list(left.shape),
        "maxDifference": float(delta[index]),
        "index": [int(i) for i in index],
        "python": float(left[index]),
        "browser": float(right[index]),
    }


def main() -> None:
    """Read only generated local tensors and produce reviewable numeric evidence."""
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--graph", action="store_true")
    cli.add_argument("--output", type=Path, default=ROOT / "tensor-summary.json")
    args = cli.parse_args()
    native = json.loads((ROOT / "native-tensors.json").read_text())
    browser = json.loads((ROOT / "browser-tensors.json").read_text())
    results: list[dict[str, object]] = []
    for dataset in browser:
        reference = next(d for d in native if d["name"] == dataset["name"])
        for group in dataset["traces"]:
            expected = next(t for t in reference["traces"] if t["norm"] == group["norm"])
            shape = expected["logitDims"]
            logits = np.asarray(group["logits"]).reshape(*shape[:2], 10)[..., : shape[2]]
            results.append(
                {
                    "dataset": dataset["name"],
                    "seed": dataset["seed"],
                    "norm": group["norm"],
                    "encoded": difference(expected["encoded"], group["encoded"]),
                    "nativeMember0": expected["group"][0],
                    "browserMember0": group["group"][0],
                    "X": difference(
                        np.asarray(expected["X"]).reshape(expected["dims"]),
                        np.asarray(group["X"]).reshape(group["dims"]),
                    ),
                    "y": difference(expected["y"], group["y"]),
                    "logits": difference(np.asarray(expected["logits"]).reshape(shape), logits),
                }
            )
    evidence: dict[str, object] = {"estimators": 4, "boundaries": results}
    if args.graph:
        ort = importlib.import_module("onnxruntime")
        session = ort.InferenceSession(
            str(ROOT / "debug-weights/onnx/model.onnx"), providers=["CPUExecutionProvider"]
        )
        graph_results: list[dict[str, object]] = []
        for dataset in json.loads((ROOT / "graph-tensors.json").read_text()):
            for group in dataset["traces"]:
                batch = group["dims"][0]
                outputs = session.run(
                    None,
                    {
                        "X": np.asarray(group["X"], dtype=np.float32).reshape(group["dims"]),
                        "y_train": np.asarray(group["y"], dtype=np.float32).reshape(batch, -1),
                    },
                )
                boundaries = {
                    info.name: difference(value.ravel(), group["stages"][info.name])
                    for info, value in zip(session.get_outputs(), outputs, strict=True)
                    if info.name != "logits"
                }
                reference = next(d for d in native if d["name"] == dataset["name"])
                expected = next(t for t in reference["traces"] if t["norm"] == group["norm"])
                cpu_outputs = dict(
                    zip((info.name for info in session.get_outputs()), outputs, strict=True)
                )
                native_comparison = {
                    name: difference(
                        np.asarray(expected["stages"][stage]["data"]).reshape(-1, width)[-1],
                        cpu_outputs[name].ravel(),
                    )
                    for name, stage, width in (("column2", "columns", 128), ("row", "rows", 512))
                }
                graph_results.append(
                    {
                        "dataset": dataset["name"],
                        "norm": group["norm"],
                        "onnxCpuVsWebGPU": boundaries,
                        "nativeVsOnnxCpu": native_comparison,
                    }
                )
        evidence["graphBoundaries"] = graph_results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
