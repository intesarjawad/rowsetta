from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from rowsetta.core.distill import fit_student
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table
from scripts import bench_active, bench_common
from scripts.bench_active import Acquisition, calibration, run_trajectory, scores
from scripts.bench_common import Observation, atomic_json, load_checkpoint, session
from scripts.bench_identity import identity
from scripts.check_drift import drift_exceeded
from scripts.render_bench import active_svg, render
from tests.unit.test_distill import labelled


def test_random_split_is_reproducible_disjoint_and_blind() -> None:
    table, first = session("penguins", 7)
    _, second = session("penguins", 7)
    assert first.human == second.human
    assert first.eval == second.eval
    assert len(first.eval) == 103
    assert not set(first.human) & set(first.eval)
    assert all(list(first.human.values()).count(label) == 2 for label in first.classes)
    assert len(table.frame) == 344


def test_budget_paths_and_resume_preserve_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def probabilities(_: str, table: Table, store: LabelStore, _seed: int) -> NDArray[np.float64]:
        assert not set(store.human) & set(store.eval)
        assert list(store.human) == sorted(store.human)
        return np.full((len(table.frame), len(store.classes)), 1 / len(store.classes))

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "first"))
    monkeypatch.setattr(bench_active, "probabilities", probabilities)
    config = Acquisition(7, "forest", "random")
    observations = run_trajectory("penguins", [10, 20], config)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "second"))
    direct = run_trajectory("penguins", [20], config)[0]
    assert direct.human == observations[-1].human
    assert list(direct.human) == sorted(direct.human)
    assert direct.eval_rows == observations[-1].eval_rows
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "third"))
    run_trajectory("penguins", [10], config)
    resumed = run_trajectory("penguins", [10, 20], config)[-1]
    assert resumed.human == direct.human
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "second"))

    def unavailable(*_: object) -> NDArray[np.float64]:
        pytest.fail("A completed checkpoint must not refit")

    monkeypatch.setattr(bench_active, "probabilities", unavailable)
    assert run_trajectory("penguins", [20], config)[0] == direct


def test_checkpoint_key_includes_data_settings_and_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(bench_common, "fingerprint", lambda: "first")
    first = bench_common.checkpoint_path("active", {"budget": 20})
    assert first != bench_common.checkpoint_path("active", {"budget": 50})
    monkeypatch.setattr(bench_common, "fingerprint", lambda: "second")
    assert first != bench_common.checkpoint_path("active", {"budget": 20})
    assert load_checkpoint(first, Observation) is None
    atomic_json(first, {"broken": True})
    with pytest.raises(ValueError, match="validation errors"):
        load_checkpoint(first, Observation)


def test_scores_do_not_count_abstentions_as_errors() -> None:
    assert scores(["a", "b", "b"], ["a", None, "a"]) == {
        "accuracy": 0.5,
        "balanced_accuracy": 0.5,
        "answered": 2,
        "total": 3,
    }
    assert scores(["a"], [None])["accuracy"] is None
    assert calibration(np.array([[1.0, 0.0], [0.0, 1.0]]), ["a", "b"], ("a", "b")) == 0


def test_renderer_and_drift_boundary_are_deterministic() -> None:
    document = bench_common.DOCUMENT.validate_json(bench_common.BENCH_JSON.read_text())
    assert render(document) == render(document)
    assert active_svg(document) == active_svg(document)
    assert not drift_exceeded(0.90, 0.88)
    assert drift_exceeded(0.90, 0.879)


@pytest.mark.native
def test_sql_identity_preserves_best_first_leaf_order() -> None:
    labels = ["a"] * 20 + ["b"] * 5 + ["a"] * 2 + ["b"] * 30 + ["a"] * 10
    table, store, proposals = labelled(
        pd.DataFrame({"x": np.arange(len(labels)), "answer": labels})
    )
    student = fit_student(table, store, proposals)
    measured = identity(student, "answer")
    expected = {"identical": len(labels), "rows_checked": len(labels), "identity_rate": 1.0}
    assert measured["duckdb"] == expected
    assert measured["sqlite"] == expected
