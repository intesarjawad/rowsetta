import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rowsetta.browser_shell import (
    BROWSER_MAX_BYTES,
    BrowserRequest,
    BrowserShell,
    browser_metadata,
    within_browser_fit_limit,
)
from rowsetta.core.lite_teacher import LiteTeacher


@pytest.fixture
def shell() -> BrowserShell:
    shell = BrowserShell(LiteTeacher(), browser_metadata("2026-11-11"))
    path = Path(__file__).resolve().parents[2] / "src/rowsetta/datasets/penguins.csv"
    shell.workspace.load(path.read_bytes(), path.name, max_rows=2000)
    shell.workspace.set_target("species", ("Adelie", "Chinstrap", "Gentoo"))
    return shell


def test_full_model_fit_limit_boundary() -> None:
    assert within_browser_fit_limit(1250, 16)
    assert not within_browser_fit_limit(1251, 16)
    assert not within_browser_fit_limit(1, 101)
    assert not within_browser_fit_limit(-1, 2)


def test_browser_masks_target_and_eval_rows(shell: BrowserShell) -> None:
    state = shell.state()
    assert state["human"] == {}
    rows = shell.workspace.require_table().frame.groupby("species").groups
    for label, ids in rows.items():
        for row in ids[:2]:
            shell.execute(BrowserRequest(action="label", row=int(row), label=str(label)))
    assert shell.workspace.proposals is not None
    reserved = shell.workspace.next_eval()
    public = shell.state()
    proposals = public["proposals"]
    assert isinstance(proposals, dict)
    assert reserved not in proposals
    page = shell.table_page(0, 100)
    assert '"species": null' in json.dumps(page)
    generation = shell.workspace.generation
    shell.execute(BrowserRequest(action="undo"))
    assert shell.workspace.generation > generation
    assert shell.workspace.proposals is None


def test_browser_sql_certificate_names_the_actual_teacher(shell: BrowserShell) -> None:
    rows = shell.workspace.require_table().frame.groupby("species").groups
    for label, ids in rows.items():
        for row in ids[:2]:
            shell.workspace.set_label(int(row), str(label), "human")
    shell.refit()
    shell.execute(BrowserRequest(action="distill"))
    sql = shell.execute(BrowserRequest(action="export"))
    assert isinstance(sql, str)
    assert "lite model (random forest), not TabICLv2" in sql
    assert "not executed" in sql.lower()
    assert "browser demo" in sql
    assert 'AS "predicted_species"' in sql
    assert isinstance(shell.execute(BrowserRequest(action="audit")), dict)
    assert isinstance(shell.execute(BrowserRequest(action="export", format="json")), str)
    assert isinstance(shell.execute(BrowserRequest(action="export", format="python")), str)
    assert isinstance(shell.execute(BrowserRequest(action="export", format="dbt")), dict)


def test_browser_rejects_column_prefill_and_invalid_label(shell: BrowserShell) -> None:
    response = json.loads(shell.call('{"action":"target","target":"species","classes":[]}'))
    assert response["ok"] is False
    assert "local-app feature" in response["error"]["error"]
    response = json.loads(shell.call('{"action":"label","row":99999,"label":"Adelie"}'))
    assert response["ok"] is False
    assert shell.workspace.max_bytes == BROWSER_MAX_BYTES


def test_external_teacher_keeps_eval_rows_out_of_training(shell: BrowserShell) -> None:
    assert shell.refit_input() == "null"
    rows = shell.workspace.require_table().frame.groupby("species").groups
    for label, ids in rows.items():
        for row in ids[:2]:
            shell.call(
                json.dumps({"action": "label", "row": int(row), "label": str(label)}), refit=False
            )
    reserved = shell.workspace.next_eval()
    assert reserved is not None
    shell.workspace.set_label(reserved, "Adelie", "eval")
    data = json.loads(shell.refit_input())
    assert len(data["train"]) == 6
    assert len(data["test"]) == 344
    assert len(data["labels"]) == 6
    result = {
        "generation": data["generation"],
        "classes": ["Adelie", "Chinstrap", "Gentoo"],
        "probabilities": [[0.2, 0.3, 0.5]] * 344,
    }
    shell.publish_refit(json.dumps(result))
    public = shell.state()["proposals"]
    assert isinstance(public, dict)
    assert reserved not in public
    assert shell.workspace.require_proposals().proba.loc[reserved].to_numpy().tolist() == [
        0.2,
        0.3,
        0.5,
    ]
    assert shell.refit_input() == "null"
    result["probabilities"] = [[0.2, 0.3, 0.4]] * 344
    with pytest.raises(ValueError, match="sum to one"):
        shell.publish_refit(json.dumps(result))
    result["generation"] = -1
    with pytest.raises(ValueError, match="generation"):
        shell.publish_refit(json.dumps(result))


def test_full_model_certificate_metadata() -> None:
    metadata = browser_metadata("2026-11-11", full_model=True)
    assert metadata.teacher_version == "TabICLv2 (WebGPU)"


def test_read_only_call_does_not_retry_a_failed_external_refit(shell: BrowserShell) -> None:
    rows = shell.workspace.require_table().frame.groupby("species").groups
    for label, ids in rows.items():
        for row in ids[:2]:
            shell.workspace.set_label(int(row), str(label), "human")
    response = json.loads(shell.call('{"action":"table"}', refit=False))
    assert response["refit"] == "null"
    assert "rows" in response["value"]
    assert shell.workspace.proposals is None


@pytest.mark.native
def test_browser_startup_does_not_import_optional_routes() -> None:
    code = """
import sys
import rowsetta.browser_shell
for name in ('rowsetta.core.export.dbt', 'rowsetta.core.export.json',
             'rowsetta.core.export.python', 'rowsetta.core.leaks'):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_invalid_dbt_target_returns_recovery_before_fitting(shell: BrowserShell) -> None:
    shell.workspace.set_target("Risk category", ("a", "b"))
    before = shell.workspace.require_store().to_json()
    response = json.loads(shell.call('{"action":"export","format":"dbt"}'))
    assert response["ok"] is False
    assert "dbt identifier" in response["error"]["error"]
    assert "SQL, Python or JSON" in response["error"]["next_step"]
    assert "Traceback" not in json.dumps(response)
    assert shell.workspace.require_store().to_json() == before


@pytest.mark.parametrize("csv", ["", "x,answer\n"])
def test_browser_rejected_empty_load_preserves_labels(shell: BrowserShell, csv: str) -> None:
    shell.workspace.set_label(0, "Adelie", "human")
    before = shell.workspace.require_store().to_json()
    response = json.loads(shell.call(json.dumps({"action": "load", "csv": csv})))
    assert response["ok"] is False
    assert "at least one data row" in response["error"]["error"]
    assert shell.workspace.require_store().to_json() == before


@pytest.mark.parametrize(
    "values",
    [
        [1e-12, 2e-12, 3e-12, 4e-12, 5e-12, 6e-12],
        [1.2345678901234567, -2.345678901234567, 1e-100, 1e100, 0.0, -1e-100],
    ],
)
def test_numeric_cells_round_trip_for_training_prediction_and_display(values: list[float]) -> None:
    shell = BrowserShell(None, browser_metadata("2026-11-12"))
    data = "x,y\n" + "".join(
        f"{value!r},{'a' if i < 3 else 'b'}\n" for i, value in enumerate(values)
    )
    shell.workspace.load(data.encode(), "numbers.csv", max_rows=2000)
    shell.workspace.set_target_from_column("y")
    frame = shell.workspace.require_table().frame
    expected = frame.x.tolist()
    assert expected == values
    inputs = json.loads(shell.refit_input())
    assert inputs["train"] == [[value] for value in expected]
    assert inputs["test"] == [[value] for value in expected]
    page = json.loads(json.dumps(shell.table_page(0, 100)))
    assert [row["x"] for row in page["rows"]] == expected


@pytest.mark.native
def test_refit_input_round_trips_through_javascript(shell: BrowserShell) -> None:
    shell.workspace.load(b"x,y\n1e-12,a\n2e-12,a\n3e-12,b\n4e-12,b\n", "numbers.csv", max_rows=2000)
    shell.workspace.set_target_from_column("y")
    encoded = shell.refit_input()
    node = shutil.which("node")
    assert node is not None
    transported = subprocess.run(
        [
            node,
            "-e",
            (
                "let text=''; process.stdin.on('data', chunk => text += chunk); "
                "process.stdin.on('end', () => "
                "process.stdout.write(JSON.stringify(JSON.parse(text))));"
            ),
        ],
        input=encoded,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    inputs = json.loads(transported)
    assert inputs == json.loads(encoded)
    assert inputs["train"] == [[1e-12], [2e-12], [3e-12], [4e-12]]
    assert inputs["test"] == inputs["train"]


def test_browser_json_keeps_missing_and_nonfinite_cells_null(shell: BrowserShell) -> None:
    shell.workspace.load(b"x,y\ninf,a\n-inf,a\n,b\n1e-12,b\n", "missing.csv", max_rows=2000)
    shell.workspace.set_target_from_column("y")
    expected = [[None], [None], [None], [1e-12]]
    payload = json.loads(shell.refit_input())
    assert payload["train"] == expected
    assert payload["test"] == expected
    page = shell.table_page(0, 100)
    assert json.loads(json.dumps(page, allow_nan=False))["rows"] == [
        {"x": row[0], "y": None} for row in expected
    ]
