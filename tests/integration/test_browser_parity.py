import hashlib
import json
from pathlib import Path

import pytest

from scripts import mirror_onnx
from scripts.compare_parity_tensors import difference


def test_tensor_summary_preserves_the_first_maximum_coordinate() -> None:
    result = difference([[1.0, 2.0], [3.0, 4.0]], [[1.0, 2.0], [3.0, 4.25]])
    assert result == {
        "shape": [2, 2],
        "maxDifference": 0.25,
        "index": [1, 1],
        "python": 4.0,
        "browser": 4.25,
    }
    with pytest.raises(ValueError, match="shapes differ"):
        difference([1.0], [[1.0]])


def test_local_mirror_checks_diagnostic_weights_on_cached_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = {"onnx/fp16": b"half weights", "onnx/fp32": b"full weights"}
    pins = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    monkeypatch.setattr(mirror_onnx, "FILES", {"onnx/fp16": pins["onnx/fp16"]})
    monkeypatch.setattr(mirror_onnx, "FP32", {"onnx/fp32": pins["onnx/fp32"]})
    (tmp_path / "onnx").mkdir()
    (tmp_path / "README.md").write_text("Local fixture")
    (tmp_path / "config.json").write_text(
        json.dumps({"files": {name: {"sha256": digest} for name, digest in pins.items()}})
    )
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    mirror_onnx.stage(tmp_path, fp32=True)
    (tmp_path / "onnx/fp32").write_bytes(b"corrupted weights")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        mirror_onnx.stage(tmp_path, fp32=True)
