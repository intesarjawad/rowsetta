import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import JsonValue, TypeAdapter

from rowsetta.api.security import SessionSecurity
from rowsetta.app import LaunchCsv, create_app
from rowsetta.core.errors import FileTooLargeError, UnknownColumnsError
from rowsetta.teachers.fake import FakeTeacher
from tests.integration.api_support import DATASET, LAUNCH_CODE, authenticate, body, wait_refit

SESSION = Path(__file__).parents[1] / "fixtures/penguins.rowsetta.json"


def launch(csv: LaunchCsv) -> FastAPI:
    return create_app(
        teacher=FakeTeacher(),
        security=SessionSecurity(LAUNCH_CODE),
        static_dir=csv.path.parent / "absent-static",
        data_dir=csv.path.parent / "sessions",
        csv=csv,
    )


@asynccontextmanager
async def opened(csv: LaunchCsv) -> AsyncGenerator[httpx.AsyncClient]:
    app = launch(csv)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client,
    ):
        await authenticate(client)
        yield client


def copy_dataset(tmp_path: Path) -> Path:
    csv = tmp_path / "penguins.csv"
    csv.write_bytes(DATASET.read_bytes())
    return csv


def column_names(table: dict[str, JsonValue]) -> list[str]:
    columns = TypeAdapter(list[dict[str, JsonValue]]).validate_python(table["columns"])
    return [str(column["name"]) for column in columns]


def test_open_loads_the_csv_and_keeps_only_the_selected_columns(tmp_path: Path) -> None:
    csv = LaunchCsv(
        copy_dataset(tmp_path), session_beside=True, columns=("species", "island", "sex")
    )

    async def run() -> None:
        async with opened(csv) as client:
            assert body(await client.get("/state"))["file_name"] == "penguins.csv"
            table = body(await client.get("/table?size=1"))
            assert column_names(table) == ["species", "island", "sex"]
            assert table["source_rows"] == 344

    asyncio.run(run())


def test_open_resumes_the_adjacent_session_and_refits_at_start(tmp_path: Path) -> None:
    path = copy_dataset(tmp_path)
    session = json.loads(SESSION.read_text())
    session["source"]["file_name"] = path.name
    path.with_suffix(".rowsetta.json").write_text(json.dumps(session))

    async def run() -> None:
        async with opened(LaunchCsv(path, session_beside=True)) as client:
            state = await wait_refit(client)
            assert state["target"] == "species"
            assert state["eval_count"] == 20
            assert state["proposals"]

    asyncio.run(run())
    assert not (tmp_path / "sessions").exists()


def test_bundled_csv_keeps_its_session_in_the_data_dir(tmp_path: Path) -> None:
    async def run() -> None:
        async with opened(LaunchCsv(copy_dataset(tmp_path), session_beside=False)) as client:
            assert body(await client.get("/table?size=1"))["source_rows"] == 344

    asyncio.run(run())
    assert list((tmp_path / "sessions").glob("*/penguins.csv"))


def test_open_limit_is_set_by_the_caller(tmp_path: Path) -> None:
    path = copy_dataset(tmp_path)
    size = path.stat().st_size

    with pytest.raises(FileTooLargeError) as raised:
        launch(LaunchCsv(path, session_beside=True, max_bytes=size - 1))
    assert raised.value.file_name == str(path)

    async def run() -> None:
        async with opened(LaunchCsv(path, session_beside=True, max_bytes=size)) as client:
            assert body(await client.get("/table?size=1"))["source_rows"] == 344

    asyncio.run(run())


def test_open_rejects_unknown_columns_naming_the_path_as_given(tmp_path: Path) -> None:
    csv = LaunchCsv(copy_dataset(tmp_path), session_beside=True, columns=("species", "isle"))

    with pytest.raises(UnknownColumnsError) as raised:
        launch(csv)
    assert raised.value.unknown == ("isle",)
    assert raised.value.file_name == str(csv.path)
