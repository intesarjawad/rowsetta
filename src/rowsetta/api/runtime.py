import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from rowsetta.api.errors import ApiError, ModelUnavailableError, error_body
from rowsetta.api.worker import RefitWorker
from rowsetta.core.errors import UserError
from rowsetta.core.teacher import Proposals, Teacher
from rowsetta.core.workspace import Workspace
from rowsetta.teachers.fake import FakeTeacher

EVENT_QUEUE_SIZE = 64
HEARTBEAT_SECONDS = 15
REFIT_PROGRESS_SECONDS = 1


@dataclass(frozen=True)
class Event:
    """A public event name and JSON payload without source data or credentials."""

    name: str
    data: dict[str, object]


class WorkspaceRuntime:
    """Run serialized refits outside the request loop and broadcast their progress."""

    def __init__(self, workspace: Workspace, teacher: Teacher) -> None:
        self.workspace = workspace
        self.fake_teacher = isinstance(teacher, FakeTeacher)
        self.worker = RefitWorker(teacher)
        self.failure: UserError | None = None
        self._latest_progress = (0, 0)
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule(self) -> None:
        """Snapshot ready sessions and supersede publication of older generations."""
        self.failure = None
        workspace = self.workspace
        if workspace.store is None or workspace.missing_labels():
            return
        generation = workspace.generation
        loop = asyncio.get_running_loop()

        def progress(done: int, total: int) -> None:
            loop.call_soon_threadsafe(self._progress, generation, done, total)

        future = self.worker.refit(
            workspace.require_table(), workspace.require_store(), on_progress=progress
        )
        self.emit(Event("refit_started", {"generation": generation}))
        self._latest_progress = (
            0,
            len(workspace.require_table().frame) - len(workspace.require_store().human),
        )
        task = asyncio.create_task(self._finish(asyncio.wrap_future(future), generation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        """Finish owned work before releasing the teacher thread."""
        await asyncio.gather(*self._tasks)
        await asyncio.to_thread(self.worker.close)

    def emit(self, event: Event) -> None:
        """Bound memory for slow or disconnected subscribers."""
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def events(self) -> AsyncIterator[Event | None]:
        """Subscribe until cancelled; heartbeats keep idle connections observable."""
        queue: asyncio.Queue[Event] = asyncio.Queue(EVENT_QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield None
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield None
        finally:
            self._subscribers.remove(queue)

    def _progress(self, generation: int, done: int, total: int) -> None:
        if generation == self.workspace.generation:
            self._latest_progress = (done, total)
            self.emit(Event("progress", {"done": done, "total": total}))

    async def _finish(self, future: asyncio.Future[Proposals | None], generation: int) -> None:
        try:
            while not future.done():
                done, _ = await asyncio.wait((future,), timeout=REFIT_PROGRESS_SECONDS)
                if not done:
                    self._progress(generation, *self._latest_progress)
            result = future.result()
        except (Exception, SystemExit) as error:
            if generation == self.workspace.generation:
                logging.getLogger(__name__).exception("Refit failed")
                self.failure = _refit_error(error)
                self.emit(Event("refit_failed", error_body(self.failure)))
            return
        if result is not None and self.workspace.publish(result, generation):
            self.emit(Event("refit_done", {"generation": generation}))


def _refit_error(error: Exception | SystemExit) -> UserError:
    if isinstance(error, UserError):
        return error
    if isinstance(error, (RuntimeError, OSError, SystemExit)):
        return ModelUnavailableError()
    return ApiError("The refit could not be completed.", status_code=500)
