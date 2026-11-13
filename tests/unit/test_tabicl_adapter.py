import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from rowsetta.core.teacher import TEACHER_N_ESTIMATORS, Teacher
from rowsetta.teachers import checkpoint, tabicl


def test_adapter_verifies_path_and_retains_class_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verified = tmp_path / "verified.ckpt"
    arguments: dict[str, object] = {}

    class StubClassifier:
        classes_: NDArray[np.str_] = np.array(["z", "a"])

        def __init__(self, **kwargs: object) -> None:
            arguments.update(kwargs)

        def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
            assert len(x) == len(y) == 4

        def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
            return np.tile([0.8, 0.2], (len(x), 1))

    monkeypatch.setitem(sys.modules, "tabicl", SimpleNamespace(TabICLClassifier=StubClassifier))
    monkeypatch.setattr(tabicl, "checkpoint_path", lambda: verified)
    monkeypatch.setenv("ROWSETTA_DEVICE", "cpu")
    teacher: Teacher = tabicl.TabICLTeacher()
    assert arguments == {
        "n_estimators": TEACHER_N_ESTIMATORS,
        "kv_cache": True,
        "device": "cpu",
        "model_path": verified,
        "allow_auto_download": False,
        "random_state": 7,
        "verbose": False,
    }
    x = pd.DataFrame({"x": [0, 1, 2, 3]})
    teacher.fit(x, pd.Series(["z", "z", "a", "a"]))
    assert teacher.classes == ("z", "a")
    np.testing.assert_allclose(teacher.predict_proba(x), np.tile([0.8, 0.2], (4, 1)))
    tabicl.TabICLTeacher(device="mps")
    assert arguments["device"] == "mps"


def test_checkpoint_resolution_pins_revision_and_verifies_before_return(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / checkpoint.FILENAME
    verified: list[Path] = []

    class Hub:
        def hf_hub_download(self, repo_id: str, filename: str, *, revision: str) -> str:
            assert (repo_id, filename, revision) == (
                "jingang/TabICL",
                "tabicl-classifier-v2-20260212.ckpt",
                "4dcd344ece2c00be9e831fdd35bed57b5ad83e19",
            )
            return str(path)

    monkeypatch.setattr(checkpoint, "verify_checkpoint", verified.append)
    assert checkpoint.checkpoint_path(Hub()) == path
    assert verified == [path]
