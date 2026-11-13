import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter

from tests.integration.api_support import (
    DATASET,
    api,
    authenticate,
    body,
    load_penguins,
    train,
    wait_refit,
)

pytestmark = pytest.mark.native


async def penguins_flow(client: httpx.AsyncClient) -> None:
    await authenticate(client)
    missing_frontend = await client.get("/")
    assert missing_frontend.status_code == 503
    assert body(missing_frontend)["next_step"] == "make setup"
    truth = await load_penguins(client)
    need_labels = await client.post("/distill", json={"max_depth": 4})
    assert need_labels.status_code == 409
    assert body(need_labels)["missing"] == {"Adelie": 2, "Chinstrap": 2, "Gentoo": 2}
    unserved = await client.put("/labels/0", json={"label": "Adelie", "mode": "eval"})
    assert unserved.status_code == 409
    assert "random" in str(body(unserved)["error"])
    await train(client, truth)
    initial = await wait_refit(client)
    assert len(TypeAdapter(dict[str, str]).validate_python(initial["proposals"])) == 344
    await evaluate_rows(client, truth)
    assert (
        await client.put("/columns/island/excluded", json={"excluded": True})
    ).status_code == 200
    assert (await client.put("/threshold", json={"threshold": 0.1})).status_code == 200
    await wait_refit(client)
    distilled = await client.post("/distill", json={"max_depth": 3})
    assert distilled.status_code == 200, distilled.text
    assert body(distilled)["leaf_summary"]
    assert_disagreements(body(distilled), body(await client.get("/state")))
    audit = await client.get("/audit")
    assert body(audit)["leaks"] == []
    session = body(await client.get("/session"))
    assert session["threshold"] == 0.1
    assert session["excluded_columns"] == ["island"]
    for export_format in ("sql", "dbt", "python", "json"):
        response = await client.get(
            "/export", params={"format": export_format, "dialect": "duckdb"}
        )
        if response.is_error:
            body(response)
        assert response.status_code == 200, response.text
        if export_format == "json":
            assert body(response)["certificate"]
            assert '"identical": 344' in response.text
        else:
            assert "344/344 rows identical" in response.text
        assert "integration-launch-token" not in response.text
    invalidated = await client.put("/threshold", json={"threshold": 1})
    assert body(invalidated)["proposals"] == {}
    stale_export = await client.get("/export")
    assert stale_export.status_code == 409
    body(stale_export)
    await wait_refit(client)
    abstaining = body(await client.post("/distill", json={"max_depth": 1}))
    leaves = TypeAdapter(list[dict[str, JsonValue]]).validate_python(abstaining["leaf_summary"])
    assert any(leaf["label"] is None for leaf in leaves)


def assert_disagreements(distilled: dict[str, JsonValue], state: dict[str, JsonValue]) -> None:
    """The rule disagrees where an answering line's label differs from the shown answer."""
    shown = TypeAdapter(dict[int, str]).validate_python(state["human"]) | TypeAdapter(
        dict[int, str]
    ).validate_python(state["proposals"])
    abstained = set(TypeAdapter(list[int]).validate_python(state["abstained"]))
    leaves = TypeAdapter(list[dict[str, JsonValue]]).validate_python(distilled["leaf_summary"])
    expected = {
        row
        for leaf in leaves
        if leaf["label"] is not None
        for row in TypeAdapter(list[int]).validate_python(leaf["row_ids"])
        if row in shown and row not in abstained and shown[row] != leaf["label"]
    }
    found = TypeAdapter(list[int]).validate_python(distilled["disagreements"])
    assert expected
    assert set(found) == expected


async def evaluate_rows(client: httpx.AsyncClient, truth: dict[int, str]) -> None:
    for _ in range(20):
        row = TypeAdapter(int).validate_python(body(await client.get("/eval/next"))["row_id"])
        state = body(await client.get("/state"))
        assert str(row) not in TypeAdapter(dict[str, str]).validate_python(state["proposals"])
        table = body(await client.get(f"/table?page={row}&size=1"))
        rows = TypeAdapter(list[dict[str, JsonValue]]).validate_python(table["rows"])
        assert rows[0]["species"] is None
        assert "bill_length_mm" in rows[0]
        response = await client.put(f"/labels/{row}", json={"label": truth[row], "mode": "eval"})
        assert response.status_code == 200
    measured = await wait_refit(client)
    evaluation = TypeAdapter(dict[str, JsonValue]).validate_python(measured["evaluation"])
    assert evaluation["n"] == 20
    response = await client.post("/undo")
    assert body(response)["eval_count"] == 19
    undone = TypeAdapter(int).validate_python(body(await client.get("/eval/next"))["row_id"])
    assert (
        await client.put(f"/labels/{undone}", json={"label": truth[undone], "mode": "eval"})
    ).status_code == 200


def test_penguins_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROWSETTA_TEACHER", "fake")

    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await penguins_flow(client)

    asyncio.run(run())


def test_csv_upload_and_failed_replacement_preserves_session(tmp_path: Path) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            response = await client.post(
                "/table", files={"file": ("birds.csv", DATASET.read_bytes(), "text/csv")}
            )
            assert response.status_code == 200
            assert body(await client.get("/table?page=3&size=100"))["row_ids"] == list(
                range(300, 344)
            )
            malformed = await client.post(
                "/table", files={"file": ("bad.csv", b'"unterminated', "text/csv")}
            )
            assert malformed.status_code == 400
            assert "bad.csv" in str(body(malformed)["error"])
            assert body(await client.get("/table"))["total"] == 344

    asyncio.run(run())


def test_target_without_classes_takes_them_and_the_labels_from_its_column(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            truth = await load_penguins(client)
            state = body(await client.post("/target", json={"target": "species"}))
            assert state["classes"] == ["Adelie", "Chinstrap", "Gentoo"]
            assert state["human"] == {str(row): label for row, label in truth.items()}
            too_many = await client.post("/target", json={"target": "bill_length_mm"})
            assert too_many.status_code == 422
            assert "distinct values" in str(body(too_many)["error"])

    asyncio.run(run())


@pytest.mark.parametrize(
    ("method", "path", "payload", "status"),
    [
        ("GET", "/table", None, 409),
        ("POST", "/table", {"demo": "unknown"}, 422),
        ("POST", "/target", {"target": "species", "classes": ["a", "a"]}, 422),
        ("POST", "/target", {"target": "species", "classes": ["a"]}, 422),
        ("PUT", "/threshold", {"threshold": 1.1}, 422),
        ("GET", "/table?page=-1", None, 422),
        ("GET", "/export?format=invalid", None, 422),
        ("GET", "/does-not-exist", None, 404),
        ("POST", "/state", None, 405),
    ],
)
def test_error_contract(
    tmp_path: Path, method: str, path: str, payload: dict[str, object] | None, status: int
) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            response = await client.request(method, path, json=payload)
            assert response.status_code == status
            body(response)

    asyncio.run(run())


@pytest.mark.parametrize(
    "data",
    [
        b"not a multipart body",
        b"",
    ],
)
def test_incomplete_upload_has_recovery(tmp_path: Path, data: bytes) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            response = await client.post(
                "/table",
                content=data,
                headers={"Content-Type": "multipart/form-data; boundary=absent"},
            )
            assert response.status_code == 400
            body(response)

    asyncio.run(run())


def test_upload_limits_have_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            columns = ",".join(f"column_{index}" for index in range(101)).encode() + b"\n"
            response = await client.post("/table", files={"file": ("wide.csv", columns)})
            assert response.status_code == 413
            assert "--columns" in str(body(response)["next_step"])
            assert "wide.csv" in str(body(response)["next_step"])
            monkeypatch.setattr("rowsetta.api.upload.MAX_FILE_BYTES", 1)
            response = await client.post(
                "/table",
                content=b"x" * 65_538,
                headers={"Content-Type": "multipart/form-data; boundary=absent"},
            )
            assert response.status_code == 413
            assert "--max-file-mb" in str(body(response)["next_step"])

    asyncio.run(run())


def test_suspects_rank_an_existing_label_column_out_of_fold(tmp_path: Path) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            truth = await load_penguins(client)
            await train(client, truth)
            too_few = await client.get("/suspects")
            assert too_few.status_code == 409
            assert body(too_few)["missing"] == {"Adelie": 3, "Chinstrap": 3, "Gentoo": 3}
            await client.post("/target", json={"target": "species"})
            assert (await client.put("/labels/0", json={"label": "Gentoo"})).status_code == 200
            suspects = TypeAdapter(list[dict[str, JsonValue]]).validate_python(
                body(await client.get("/suspects"))["suspects"]
            )
            assert len(suspects) == len(truth)
            assert suspects[0] == suspects[0] | {"row_id": 0, "given": "Gentoo", "likely": "Adelie"}

    asyncio.run(run())


@pytest.mark.parametrize("data", [b"", b"x,answer\n"])
def test_empty_upload_does_not_replace_the_session(tmp_path: Path, data: bytes) -> None:
    async def flow() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            await load_penguins(client)
            await client.put("/labels/0", json={"label": "Adelie"})
            before = body(await client.get("/state"))
            response = await client.post("/table", files={"file": ("empty.csv", data, "text/csv")})
            assert response.status_code == 400
            assert "at least one data row" in str(body(response)["error"])
            assert body(await client.get("/state")) == before
            assert body(await client.get("/table"))["total"] == 344

    asyncio.run(flow())


def test_dbt_target_validation_precedes_missing_fit(tmp_path: Path) -> None:
    async def flow() -> None:
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            await load_penguins(client)
            await client.post("/target", json={"target": "Risk category", "classes": ["a", "b"]})
            before = body(await client.get("/state"))
            response = await client.get("/export?format=dbt")
            assert response.status_code == 422
            assert "dbt identifier" in str(body(response)["error"])
            assert "SQL, Python or JSON" in str(body(response)["next_step"])
            assert body(await client.get("/state")) == before

    asyncio.run(flow())


def test_http_table_preserves_numeric_values_and_missing_cells(tmp_path: Path) -> None:
    async def flow() -> None:
        values = [1e-12, 1.2345678901234567, -1e-100, 1e100]
        csv = "x,category\n" + "".join(f"{value!r},a\n" for value in values) + ",b\ninf,b\n-inf,b\n"
        async with api(tmp_path) as (_, client):
            await authenticate(client)
            loaded = await client.post(
                "/table", files={"file": ("numbers.csv", csv.encode(), "text/csv")}
            )
            assert loaded.status_code == 200, loaded.text
            response = await client.get("/table")
            rows = TypeAdapter(list[dict[str, JsonValue]]).validate_python(body(response)["rows"])
            assert [row["x"] for row in rows] == [*values, None, None, None]
            assert [row["category"] for row in rows] == ["a", "a", "a", "a", "b", "b", "b"]

    asyncio.run(flow())
