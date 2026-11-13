import asyncio
import os
import subprocess
import sys
from ipaddress import IPv4Address
from pathlib import Path

import httpx
import pytest

from rowsetta.api.security import SessionSecurity
from rowsetta.app import create_app
from rowsetta.teachers.fake import FakeTeacher
from tests.integration.api_support import LAUNCH_CODE, api, authenticate, body

pytestmark = pytest.mark.native


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/table",
        "/target",
        "/labels/0",
        "/undo",
        "/eval/next",
        "/columns/island/excluded",
        "/threshold",
        "/state",
        "/distill",
        "/export",
        "/audit",
        "/session",
        "/events",
    ],
)
def test_routes_require_session(tmp_path: Path, path: str) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            response = await client.get(path)
            assert response.status_code == 403
            body(response)
            query_token = await client.get(path if path == "/" else path + "?token=" + LAUNCH_CODE)
            assert query_token.status_code == 403
            body(query_token)

    asyncio.run(run())


@pytest.mark.parametrize(
    "host", ["attacker.example", "127.0.0.1.attacker.example", "localhost.attacker.example"]
)
def test_foreign_host_is_rejected_before_authentication(tmp_path: Path, host: str) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            for path in ("/health", "/state", "/?token=" + LAUNCH_CODE):
                response = await client.get(path, headers={"Host": host})
                assert response.status_code == 400
                body(response)
                assert "set-cookie" not in response.headers

    asyncio.run(run())


def test_health_and_cookie_scope(tmp_path: Path) -> None:
    async def run() -> None:
        async with api(tmp_path) as (_, client):
            assert body(await client.get("/health")) == {"ok": True}
            assert body(await client.get("/health", headers={"Host": "localhost:8787"})) == {
                "ok": True
            }
            invalid = await client.get("/?token=wrong")
            assert invalid.status_code == 403
            body(invalid)
            assert "set-cookie" not in invalid.headers
            await authenticate(client)
            assert LAUNCH_CODE not in (await client.get("/state")).text
            assert body(await client.get("/state"))["dev_states"] is False
            client.cookies.clear()
            client.cookies.set("rowsetta_session_80", "wrong")
            wrong = await client.get("/state")
            assert wrong.status_code == 403
            body(wrong)

    asyncio.run(run())


def test_launch_tokens_are_random_and_override_is_loopback_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROWSETTA_SESSION_TOKEN", raising=False)
    first, second = SessionSecurity.for_host("127.0.0.1"), SessionSecurity.for_host("127.0.0.1")
    assert len(first.token) >= 43
    assert first.token != second.token
    monkeypatch.setenv("ROWSETTA_SESSION_TOKEN", LAUNCH_CODE)
    assert SessionSecurity.for_host("127.0.0.1").token == LAUNCH_CODE
    with pytest.raises(ValueError, match=r"only allowed on 127\.0\.0\.1"):
        SessionSecurity.for_host(str(IPv4Address(0)))


def test_cli_refuses_token_on_non_loopback_bind() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from ipaddress import IPv4Address
from rowsetta.cli import main
sys.argv = ['rowsetta', 'demo', '--no-browser', '--host', str(IPv4Address(0))]
main()
""",
        ],
        env={**os.environ, "ROWSETTA_SESSION_TOKEN": LAUNCH_CODE, "ROWSETTA_TEACHER": "fake"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "ROWSETTA_SESSION_TOKEN is only allowed on 127.0.0.1" in result.stderr
    assert "Open http" not in result.stdout


def test_built_static_is_authenticated_and_states_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROWSETTA_STATES", "1")
    (tmp_path / "index.html").write_text("<html><title>Local app</title></html>")
    (tmp_path / "app.js").write_text("export const ready = true;")

    async def run() -> None:
        app = create_app(
            teacher=FakeTeacher(), security=SessionSecurity(LAUNCH_CODE), static_dir=tmp_path
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as client,
        ):
            unauthenticated = await client.get("/app.js")
            assert unauthenticated.status_code == 403
            body(unauthenticated)
            await authenticate(client)
            assert (await client.get("/")).status_code == 200
            assert "ready" in (await client.get("/app.js")).text
            assert body(await client.get("/state"))["dev_states"] is True
            missing = await client.get("/missing.js")
            assert missing.status_code == 404
            body(missing)

    asyncio.run(run())


def test_unexpected_error_has_recovery_without_details(tmp_path: Path) -> None:
    async def run() -> None:
        async with api(tmp_path) as (app, client):

            @app.get("/broken")
            async def broken() -> None:
                message = "private implementation detail"
                raise RuntimeError(message)

            await authenticate(client)
            response = await client.get("/broken")
            assert response.status_code == 500
            body(response)
            assert "private implementation detail" not in response.text

    asyncio.run(run())
