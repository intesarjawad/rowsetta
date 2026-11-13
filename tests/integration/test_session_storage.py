import asyncio
from hashlib import sha256
from pathlib import Path

import httpx
import pytest

from tests.integration.api_support import DATASET, api, authenticate, body

pytestmark = pytest.mark.native


@pytest.mark.parametrize("demo", [True, False])
def test_sessions_resume_across_app_restarts(tmp_path: Path, *, demo: bool) -> None:
    async def load(client: httpx.AsyncClient) -> httpx.Response:
        if demo:
            return await client.post("/table", json={"demo": "penguins"})
        return await client.post(
            "/table", files={"file": ("../birds.csv", DATASET.read_bytes(), "text/csv")}
        )

    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            assert (await load(client)).status_code == 200
            assert (
                await client.post(
                    "/target", json={"target": "species", "classes": ["Adelie", "Gentoo"]}
                )
            ).status_code == 200
            assert (
                await client.put("/labels/0", json={"label": "Adelie", "mode": "human"})
            ).status_code == 200
            served = body(await client.get("/eval/next"))["row_id"]
            previous = (await client.get("/session")).json()
        folder = tmp_path / "sessions" / sha256(DATASET.read_bytes()).hexdigest()
        name = "penguins.csv" if demo else "birds.csv"
        assert (folder / name).read_bytes() == DATASET.read_bytes()
        assert previous["source"]["file_name"] == name
        assert (folder / Path(name).with_suffix(".rowsetta.json")).is_file()
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            response = await load(client)
            assert response.status_code == 200
            assert body(response)["human"] == {"0": "Adelie"}
            assert (await client.get("/session")).json() == previous
            assert body(await client.get("/eval/next"))["row_id"] == served
            assert body(await client.post("/undo"))["human"] == {}

    asyncio.run(run())
