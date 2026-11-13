from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from threading import Lock
from types import TracebackType
from typing import Self

import pandas as pd

from rowsetta.core.audit import Suspect, audit_labels
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table
from rowsetta.core.teacher import Proposals, Teacher, predict_table

WARMUP_ROWS = 32


class RefitWorker:
    """Serialize teacher work and publish only the newest requested generation.

    The caller owns the table as read-only data. Labels are copied at submission;
    completion futures return None for results superseded before publication.
    """

    def __init__(self, teacher: Teacher) -> None:
        self._teacher = teacher
        self._lock = Lock()
        self._refit_generation = 0
        self._proposals: Proposals | None = None
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refit")
        self.ready: Future[None] = self._executor.submit(self._warm_up)

    @property
    def refit_generation(self) -> int:
        """Return the latest requested generation, including unfinished refits."""
        with self._lock:
            return self._refit_generation

    @property
    def proposals(self) -> Proposals | None:
        """Return the last published result; its generation identifies its labels."""
        with self._lock:
            return self._proposals

    def refit(
        self,
        table: Table,
        store: LabelStore,
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Future[Proposals | None]:
        """Queue a snapshot, returning its result or raising its fitting error."""
        with self._lock:
            if self._closed:
                message = "Cannot refit after the worker has closed."
                raise RuntimeError(message)
            self._refit_generation += 1
            return self._executor.submit(
                self._refit, table, store.model_copy(deep=True), self._refit_generation, on_progress
            )

    def audit(self, table: Table, store: LabelStore) -> Future[list[Suspect]]:
        """Queue out-of-fold scoring behind refits so the teacher is never fitted concurrently."""
        with self._lock:
            if self._closed:
                message = "Cannot audit after the worker has closed."
                raise RuntimeError(message)
            return self._executor.submit(self._audit, table, store.model_copy(deep=True))

    def close(self) -> None:
        """Wait for queued work and release the executor thread."""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _warm_up(self) -> None:
        frame = pd.DataFrame({"x": range(WARMUP_ROWS)})
        labels = pd.Series(["a", "b"] * (WARMUP_ROWS // 2))
        self._teacher.fit(frame, labels)
        # TabICL may defer device work until prediction, even after fitting.
        self._teacher.predict_proba(frame)

    def _audit(self, table: Table, store: LabelStore) -> list[Suspect]:
        self.ready.result()
        return audit_labels(self._teacher, table, store)

    def _refit(
        self,
        table: Table,
        store: LabelStore,
        generation: int,
        on_progress: Callable[[int, int], None] | None,
    ) -> Proposals | None:
        self.ready.result()
        result = replace(
            predict_table(self._teacher, table, store, on_progress=on_progress),
            generation=generation,
        )
        with self._lock:
            if generation != self._refit_generation:
                return None
            self._proposals = result
            return result
