from threading import Event, get_ident

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from rowsetta.api.worker import RefitWorker
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import Table, load_csv
from rowsetta.teachers.fake import FakeTeacher

pytestmark = pytest.mark.native


@pytest.fixture
def sample() -> tuple[Table, LabelStore]:
    table = load_csv(b"x,outcome\n0,a\n1,a\n9,b\n10,b\n2,a\n8,b\n")
    store = LabelStore(
        classes=("a", "b"),
        target="outcome",
        source=SourceRef(file_name="data.csv", sha256="a" * 64, rows=6),
        human={0: "a", 1: "a", 2: "b", 3: "b"},
    )
    return table, store


class GatedTeacher(FakeTeacher):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()
        self.fits: list[tuple[int, pd.DataFrame, pd.Series]] = []

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        self.fits.append((get_ident(), x.copy(), y.copy()))
        super().fit(x, y)

    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        if len(self.fits) == 2:
            self.started.set()
            if not self.release.wait(timeout=5):
                message = "Timed out waiting to release the first refit."
                raise TimeoutError(message)
        return super().predict_proba(x)


def test_three_refits_publish_only_last_snapshot(sample: tuple[Table, LabelStore]) -> None:
    table, store = sample
    teacher = GatedTeacher()
    with RefitWorker(teacher) as worker:
        worker.ready.result(timeout=5)
        first = worker.refit(table, store)
        try:
            assert teacher.started.wait(timeout=5)
            store.set_human(4, "a")
            second = worker.refit(table, store)
            store.set_human(4, "b")
            third = worker.refit(table, store)
            store.set_human(4, None)
            assert worker.refit_generation == 3
            assert worker.proposals is None
        finally:
            teacher.release.set()
        assert first.result(timeout=5) is None
        assert second.result(timeout=5) is None
        result = third.result(timeout=5)
        assert result is not None
        assert worker.proposals is result
        assert result.generation == 3
        assert result.label[4] == "b"
        assert 4 not in result.confidence
        assert [fit[2].to_dict() for fit in teacher.fits[1:]] == [
            {0: "a", 1: "a", 2: "b", 3: "b"},
            {0: "a", 1: "a", 2: "b", 3: "b", 4: "a"},
            {0: "a", 1: "a", 2: "b", 3: "b", 4: "b"},
        ]


def test_startup_warms_once_on_same_background_thread(sample: tuple[Table, LabelStore]) -> None:
    teacher = GatedTeacher()
    teacher.release.set()
    with RefitWorker(teacher) as worker:
        worker.ready.result(timeout=5)
        assert worker.refit_generation == 0
        assert worker.proposals is None
        thread, frame, labels = teacher.fits[0]
        assert frame.shape == (32, 1)
        assert len(labels) == 32
        assert set(labels) == {"a", "b"}
        assert thread != get_ident()
        worker.refit(*sample).result(timeout=5)
        worker.refit(*sample).result(timeout=5)
        assert len(teacher.fits) == 3
        assert {fit[0] for fit in teacher.fits} == {thread}


def test_refit_errors_are_observable_and_worker_recovers(sample: tuple[Table, LabelStore]) -> None:
    table, store = sample
    with RefitWorker(FakeTeacher()) as worker:
        invalid = store.model_copy(deep=True)
        invalid.set_human(0, None)
        with pytest.raises(ValueError, match="at least 2"):
            worker.refit(table, invalid).result(timeout=5)
        assert worker.proposals is None
        result = worker.refit(table, store).result(timeout=5)
        assert result is not None
        assert result.generation == 2
        assert worker.proposals is result
    with pytest.raises(RuntimeError, match="closed"):
        worker.refit(table, store)


class FailingWarmupTeacher(FakeTeacher):
    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        super().fit(x, y)
        message = "Warm-up failed."
        raise ValueError(message)


def test_warmup_failure_prevents_publication(sample: tuple[Table, LabelStore]) -> None:
    with RefitWorker(FailingWarmupTeacher()) as worker:
        with pytest.raises(ValueError, match="Warm-up failed"):
            worker.ready.result(timeout=5)
        with pytest.raises(ValueError, match="Warm-up failed"):
            worker.refit(*sample).result(timeout=5)
        assert worker.proposals is None
