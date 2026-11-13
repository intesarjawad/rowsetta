import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import JsonValue, TypeAdapter

from rowsetta.api.security import SessionSecurity
from rowsetta.app import create_app
from rowsetta.teachers.fake import FakeTeacher

LAUNCH_CODE = "integration-launch-token"
DATASET = Path(__file__).parents[2] / "src/rowsetta/datasets/penguins.csv"
CLASSES = ("Adelie", "Chinstrap", "Gentoo")
POLL_SECONDS = 0.01
REFIT_TIMEOUT_SECONDS = 10


@asynccontextmanager
async def api(
    tmp_path: Path,
    *,
    teacher: FakeTeacher | None = None,
) -> AsyncGenerator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app(
        teacher=teacher if teacher is not None else FakeTeacher(),
        security=SessionSecurity(LAUNCH_CODE),
        static_dir=tmp_path / "absent-static",
        data_dir=tmp_path / "sessions",
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client,
    ):
        yield app, client


def body(response: httpx.Response) -> dict[str, JsonValue]:
    if response.is_error:
        error = TypeAdapter(dict[str, JsonValue]).validate_json(response.content)
        assert isinstance(error["error"], str)
        assert error["error"]
        assert isinstance(error["next_step"], str)
        assert error["next_step"]
    return TypeAdapter(dict[str, JsonValue]).validate_json(response.content)


async def authenticate(client: httpx.AsyncClient) -> None:
    response = await client.get("/", params={"token": LAUNCH_CODE})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


async def load_penguins(client: httpx.AsyncClient) -> dict[int, str]:
    assert (await client.post("/table", json={"demo": "penguins"})).status_code == 200
    table = body(await client.get("/table?size=1000"))
    rows = TypeAdapter(list[dict[str, JsonValue]]).validate_python(table["rows"])
    truth = {row: str(values["species"]) for row, values in enumerate(rows)}
    response = await client.post("/target", json={"target": "species", "classes": CLASSES})
    assert response.status_code == 200
    return truth


async def train(client: httpx.AsyncClient, truth: dict[int, str]) -> None:
    for label in CLASSES:
        for row in [row for row, answer in truth.items() if answer == label][:2]:
            response = await client.put(f"/labels/{row}", json={"label": label, "mode": "human"})
            assert response.status_code == 200, response.text


async def wait_refit(client: httpx.AsyncClient) -> dict[str, JsonValue]:
    async with asyncio.timeout(REFIT_TIMEOUT_SECONDS):
        while True:
            state = body(await client.get("/state"))
            assert state["failure"] is None, state
            if state["refit_generation"] == state["generation"]:
                return state
            await asyncio.sleep(POLL_SECONDS)
