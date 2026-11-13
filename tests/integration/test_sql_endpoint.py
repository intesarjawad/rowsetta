from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rowsetta.api import routes
from rowsetta.api.routes import SqlExportContext, sql_export_router
from rowsetta.core.distill import Feature, FeatureSpec, Student, fit_student
from rowsetta.core.export.sql import Certificate, Dialect
from tests.sql_support import certificate
from tests.unit.test_distill import ten_rows

pytestmark = pytest.mark.native


def client_for(tmp_path: Path, student: Student) -> TestClient:
    source = tmp_path / "source.csv"
    source.write_bytes(student.frame.to_csv(index=False).encode())
    context = SqlExportContext(source, student, certificate())
    app = FastAPI()
    app.include_router(sql_export_router(lambda: context))
    return TestClient(app)


@pytest.mark.parametrize("dialect", ["duckdb", "sqlite", "postgres"])
def test_endpoint_returns_verified_certificate(tmp_path: Path, dialect: Dialect) -> None:
    with client_for(tmp_path, fit_student(*ten_rows())) as client:
        response = client.get("/export", params={"format": "sql", "dialect": dialect})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/sql")
    assert "Execution: DuckDB " in response.text
    assert "10/10 rows identical" in response.text
    assert "not executed" not in response.text


def test_endpoint_withholds_corrupted_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    original = routes.to_sql

    def corrupted(student: Student, *, dialect: Dialect, certificate: Certificate) -> str:
        return original(student, dialect=dialect, certificate=certificate).replace(
            "0.5000000298023224", "1.5"
        )

    monkeypatch.setattr(routes, "to_sql", corrupted)
    with client_for(tmp_path, fit_student(*ten_rows())) as client:
        response = client.get("/export?format=sql&dialect=sqlite")
    assert response.status_code == 500
    assert response.json()["row_id"] == 5
    assert "source row 5" in response.json()["error"]
    assert response.json()["next_step"].startswith("rowsetta ")
    assert "source row 5" in caplog.text
    assert "SELECT" not in response.text


def test_endpoint_returns_datetime_recovery(tmp_path: Path) -> None:
    student = replace(
        fit_student(*ten_rows()), feature_spec=FeatureSpec((Feature("x", "datetime"),))
    )
    with client_for(tmp_path, student) as client:
        response = client.get("/export")
    assert response.status_code == 422
    assert "'x'" in response.json()["error"]
    assert "exclude" in response.json()["next_step"]
