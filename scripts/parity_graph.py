"""Expose the final row/feature vector at each ONNX boundary, for a local bisect.

Run with: uv run --with onnx==1.22.0 python scripts/parity_graph.py
The input graph must first be staged with mirror_onnx.py --fp32.
"""

import hashlib
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend/public/spike"
BOUNDARIES = {
    "projection": "/col_embedder/in_linear/Where_output_0",
    "column0": "/col_embedder/tf_col/blocks.0/Where_1_output_0",
    "column1": "/col_embedder/tf_col/blocks.1/Where_1_output_0",
    "column2": "/col_embedder/tf_col/blocks.2/Where_1_output_0",
    "row": "/row_interactor/Reshape_2_output_0",
}


def main() -> None:
    """Keep weights intact; add only observation outputs to an ignored local graph."""
    onnx = importlib.import_module("onnx")
    model = onnx.load(ROOT / "weights/onnx/model.onnx")
    helper = onnx.helper
    outputs = {output for node in model.graph.node for output in node.output}
    for name, source in BOUNDARIES.items():
        if source not in outputs:
            message = f"Missing pinned graph boundary: {source}"
            raise ValueError(message)
        width = 512 if name == "row" else 128
        model.graph.initializer.extend(
            [
                helper.make_tensor(f"{name}_shape", onnx.TensorProto.INT64, [2], [-1, width]),
                helper.make_tensor(f"{name}_index", onnx.TensorProto.INT64, [1], [-1]),
            ]
        )
        model.graph.node.extend(
            [
                helper.make_node("Reshape", [source, f"{name}_shape"], [f"{name}_flat"]),
                helper.make_node("Gather", [f"{name}_flat", f"{name}_index"], [name], axis=0),
            ]
        )
        model.graph.output.append(
            helper.make_tensor_value_info(name, onnx.TensorProto.FLOAT, [1, width])
        )
    folder = ROOT / "debug-weights"
    (folder / "onnx").mkdir(parents=True, exist_ok=True)
    path = folder / "onnx/model.onnx"
    onnx.save(model, path)
    config = json.loads((ROOT / "weights/config.json").read_text())
    config["files"]["onnx/model.onnx"] = {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (folder / "config.json").write_text(json.dumps(config))
    print(path)


if __name__ == "__main__":
    main()
