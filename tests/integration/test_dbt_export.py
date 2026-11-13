import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import duckdb
import numpy as np
import pytest

from rowsetta.core.distill import Count, Coverage
from rowsetta.core.export.dbt import to_dbt
from tests.integration.test_sql_export import demo_student
from tests.sql_support import certificate, predictions

pytestmark = pytest.mark.native


@pytest.mark.parametrize("quoted_labels", [False, True])
def test_dbt_build_penguins_and_coverage_drift(tmp_path: Path, *, quoted_labels: bool) -> None:
    student = demo_student("penguins", "species")
    if quoted_labels:
        student.tree.classes_ = np.array([str(label) + "'s" for label in student.tree.classes_])
        student = replace(
            student,
            teacher_labels={row: label + "'s" for row, label in student.teacher_labels.items()},
        )
    expected = student.predict(student.frame)
    answered = sum(label is not None for label in expected)
    assert 0 < answered < len(expected)
    facts = replace(
        certificate(),
        target="species",
        classes=tuple(str(label) for label in student.tree.classes_),
        row_count=len(expected),
        tree_depth=student.tree.get_depth(),
        tree_leaves=student.tree.get_n_leaves(),
        abstention_threshold=student.threshold,
        in_sample=Count(
            sum(
                label == student.teacher_labels[row]
                for row, label in enumerate(expected)
                if label is not None
            ),
            answered,
            Coverage(answered, len(expected)),
        ),
    )
    files = to_dbt(student, source="penguins", certificate=facts)
    column_types = dict.fromkeys(student.frame.select_dtypes(include="number").columns, "DOUBLE")
    files["dbt_project.yml"] = json.dumps(
        {
            "name": "export_test",
            "version": "1.0.0",
            "config-version": 2,
            "profile": "export_test",
            "model-paths": ["models"],
            "seed-paths": ["seeds"],
            "test-paths": ["tests"],
            "seeds": {"export_test": {"penguins": {"+column_types": column_types}}},
        }
    )
    database = tmp_path / "rules.duckdb"
    files["profiles.yml"] = json.dumps(
        {
            "export_test": {
                "target": "local",
                "outputs": {
                    "local": {
                        "type": "duckdb",
                        "path": str(database),
                        "threads": 1,
                    }
                },
            }
        }
    )
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    seed = tmp_path / "seeds/penguins.csv"
    seed.parent.mkdir()
    student.frame.to_csv(seed, index=False)

    passing = dbt_build(tmp_path)
    (tmp_path / "passing-build.log").write_text(passing.stdout + passing.stderr)
    assert passing.returncode == 0, passing.stdout + passing.stderr
    with duckdb.connect(str(database)) as connection:
        result = connection.execute("SELECT * FROM species_rule").fetchdf()
    assert predictions(result, "species") == expected
    assert "species_rule_coverage" in passing.stdout
    assert "ERROR=0" in passing.stdout

    abstaining_row = expected.index(None)
    drifted = student.frame.iloc[[abstaining_row] * len(student.frame)]
    assert student.predict(drifted) == [None] * len(drifted)
    drifted.to_csv(seed, index=False)
    failing = dbt_build(tmp_path)
    (tmp_path / "failing-build.log").write_text(failing.stdout + failing.stderr)
    assert failing.returncode != 0, failing.stdout + failing.stderr
    results = json.loads((tmp_path / "target/run_results.json").read_text())["results"]
    failed = [
        result for result in results if result["status"] != "success" and result["status"] != "pass"
    ]
    assert len(failed) == 1, failing.stdout + failing.stderr
    assert failed[0]["unique_id"] == "test.export_test.species_rule_coverage"
    assert failed[0]["status"] == "fail"
    assert failed[0]["failures"] == 1


def dbt_build(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            shutil.which("uv") or "uv",
            "run",
            "--locked",
            "dbt",
            "build",
            "--no-use-colors",
            "--no-partial-parse",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "DBT_PROJECT_DIR": str(project),
            "DBT_PROFILES_DIR": str(project),
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        },
    )
