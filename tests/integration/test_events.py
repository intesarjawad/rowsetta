import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from numpy.typing import NDArray
from pydantic import JsonValue, TypeAdapter
from starlette.types import Message, Scope

from rowsetta.teachers.fake import FakeTeacher
from tests.integration.api_support import (
    LAUNCH_CODE,
    api,
    authenticate,
    body,
    load_penguins,
    train,
    wait_refit,
)
from tests.unit.test_worker import GatedTeacher

pytestmark = pytest.mark.native
EVENT_TIMEOUT_SECONDS = 5


@asynccontextmanager
async def event_connection(app: FastAPI) -> AsyncGenerator[asyncio.Queue[str]]:
    chunks: asyncio.Queue[str] = asyncio.Queue()
    disconnected = asyncio.Event()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/events",
        "raw_path": b"/events",
        "query_string": b"",
        "root_path": "",
        "server": ("127.0.0.1", 8787),
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"cookie", f"rowsetta_session_80={LAUNCH_CODE}".encode()),
        ],
    }
    request_sent = False

    async def receive() -> Message:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            assert message["status"] == 200
            assert (b"content-type", b"text/event-stream; charset=utf-8") in message["headers"]
        elif message["type"] == "http.response.body" and message.get("body"):
            chunks.put_nowait(message["body"].decode())

    task = asyncio.create_task(app(scope, receive, send))
    try:
        first = await asyncio.wait_for(chunks.get(), EVENT_TIMEOUT_SECONDS)
        assert first == ": connected\n\n"
        yield chunks
    finally:
        disconnected.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def next_event(chunks: asyncio.Queue[str]) -> tuple[str, dict[str, JsonValue]]:
    chunk = await asyncio.wait_for(chunks.get(), EVENT_TIMEOUT_SECONDS)
    name, payload, _ = chunk.split("\n", maxsplit=2)
    assert name.startswith("event: ")
    assert payload.startswith("data: ")
    return name.removeprefix("event: "), TypeAdapter(dict[str, JsonValue]).validate_json(
        payload.removeprefix("data: ")
    )


async def assert_latest_events(
    client: httpx.AsyncClient, app: FastAPI, teacher: GatedTeacher
) -> None:
    await authenticate(client)
    truth = await load_penguins(client)
    async with event_connection(app) as chunks:
        await train(client, truth)
        try:
            assert await asyncio.to_thread(teacher.started.wait, EVENT_TIMEOUT_SECONDS)
            assert (await client.get("/health")).status_code == 200
            started = await next_event(chunks)
            pending_progress = await next_event(chunks)
            assert started[0] == "refit_started"
            assert pending_progress[0] == "progress"
            assert pending_progress[1]["done"] == 0
            assert pending_progress[1]["total"] == 338
            first_generation = body(await client.get("/state"))["generation"]
            response = await client.put("/labels/10", json={"label": truth[10], "mode": "human"})
            latest = body(response)["generation"]
            assert latest != first_generation
        finally:
            teacher.release.set()
        await wait_refit(client)
        events: list[tuple[str, dict[str, JsonValue]]] = [started, pending_progress]
        while not events or events[-1][0] != "refit_done":
            events.append(await next_event(chunks))
        assert events[0] == ("refit_started", {"generation": first_generation})
        assert ("refit_started", {"generation": latest}) in events
        progress = [payload for name, payload in events if name == "progress"]
        assert progress[0]["done"] == 0
        assert progress[-1]["done"] == progress[-1]["total"]
        assert events[-1] == ("refit_done", {"generation": latest})
        assert not any(
            name == "refit_done" and payload["generation"] == first_generation
            for name, payload in events
        )
    async with event_connection(app):
        assert body(await client.get("/state"))["refit_generation"] == latest


def test_sse_latest_generation_and_reconnect(tmp_path: Path) -> None:
    async def run() -> None:
        teacher = GatedTeacher()
        async with api(tmp_path, teacher=teacher) as (app, client):
            await assert_latest_events(client, app, teacher)

    asyncio.run(run())


class UnavailableTeacher(FakeTeacher):
    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        message = f"Local prediction failed for {len(x)} rows."
        raise RuntimeError(message)


class InvalidTeacher(FakeTeacher):
    def predict_proba(self, x: pd.DataFrame) -> NDArray[np.float64]:
        return np.zeros((len(x), 0))


@pytest.mark.parametrize(
    ("teacher_type", "status", "next_step"),
    [
        (UnavailableTeacher, 503, "rowsetta doctor --fix"),
        (InvalidTeacher, 500, "rowsetta demo; reopen the local app and retry."),
    ],
)
def test_refit_failure_has_recovery_in_state_sse_and_http(
    tmp_path: Path,
    teacher_type: type[FakeTeacher],
    status: int,
    next_step: str,
) -> None:
    async def run() -> None:
        async with api(tmp_path, teacher=teacher_type()) as (app, client):
            await authenticate(client)
            truth = await load_penguins(client)
            async with event_connection(app) as chunks:
                await train(client, truth)
                assert (await next_event(chunks))[0] == "refit_started"
                name, payload = await next_event(chunks)
                if teacher_type is InvalidTeacher:
                    assert name == "progress"
                    assert payload == {"done": 0, "total": 338}
                    name, payload = await next_event(chunks)
                assert name == "refit_failed"
                assert payload["next_step"] == next_step
                state = body(await client.get("/state"))
                assert state["failure"] == payload
                response = await client.post("/distill", json={"max_depth": 4})
                assert response.status_code == status
                assert body(response) == payload

    asyncio.run(run())
