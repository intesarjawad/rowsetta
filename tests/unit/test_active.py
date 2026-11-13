import numpy as np
import pytest
from numpy.typing import NDArray

from rowsetta.core.active import Predictions, next_row
from rowsetta.core.session import LabelStore, SourceRef

CLASSES = ("a", "b", "c")
ROWS = (10, 20, 30, 40, 50, 60)


@pytest.fixture
def proba() -> NDArray[np.float64]:
    return np.array(
        [
            [0.8, 0.1, 0.1],
            [0.1, 0.8, 0.1],
            [0.1, 0.1, 0.8],
            [0.45, 0.44, 0.11],
            [0.2, 0.3, 0.5],
            [0.3, 0.3, 0.4],
        ]
    )


@pytest.fixture
def store() -> LabelStore:
    return LabelStore(
        classes=CLASSES,
        target="outcome",
        source=SourceRef(file_name="data.csv", sha256="a" * 64, rows=100),
        human=dict(enumerate(CLASSES * 3)),
    )


def test_class_top_up_precedes_random_and_margin(
    store: LabelStore,
    proba: NDArray[np.float64],
) -> None:
    store.set_human(1, None)
    assert (
        next_row(
            Predictions(proba, ROWS, CLASSES), store, pick_index=4, rng=np.random.default_rng(7)
        )
        == 20
    )
    assert store.human == {row: label for row, label in enumerate(CLASSES * 3) if row != 1}


def test_smallest_margin(store: LabelStore, proba: NDArray[np.float64]) -> None:
    assert (
        next_row(
            Predictions(proba, ROWS, CLASSES), store, pick_index=0, rng=np.random.default_rng(7)
        )
        == 40
    )


def test_random_is_uniform_and_reproducible(store: LabelStore, proba: NDArray[np.float64]) -> None:
    def sequence() -> list[int]:
        rng = np.random.default_rng(7)
        return [
            next_row(Predictions(proba, ROWS, CLASSES), store, pick_index=4, rng=rng)
            for _ in range(6000)
        ]

    selected = sequence()
    assert selected == sequence()
    assert selected[0] == int(np.random.default_rng(7).choice(ROWS))
    assert all(850 < selected.count(row) < 1150 for row in ROWS)


@pytest.mark.parametrize("pick_index", [0, 4])
@pytest.mark.parametrize("top_up", [False, True])
def test_excludes_human_eval_current_and_cleared_eval(
    store: LabelStore,
    proba: NDArray[np.float64],
    *,
    pick_index: int,
    top_up: bool,
) -> None:
    store.set_human(10, "a")
    store.eval_served = [20, 30, 40]
    store.eval = {20: "b"}
    store.current_eval_row = 30
    if top_up:
        store.set_human(2, None)
    selected = next_row(
        Predictions(proba, ROWS, CLASSES),
        store,
        pick_index=pick_index,
        rng=np.random.default_rng(7),
    )
    assert selected in {50, 60}


def test_exhausted_candidates(store: LabelStore, proba: NDArray[np.float64]) -> None:
    for row in ROWS:
        store.set_human(row, "a")
    with pytest.raises(ValueError, match="No unlabelled"):
        next_row(
            Predictions(proba, ROWS, CLASSES), store, pick_index=0, rng=np.random.default_rng(7)
        )
