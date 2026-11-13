import json
from dataclasses import replace

import pandas as pd
import pytest

from rowsetta.core.distill import Count, Coverage, fit_student
from rowsetta.core.errors import UserError
from rowsetta.core.export.dbt import COVERAGE_DRIFT_MARGIN, to_dbt
from tests.sql_support import certificate, engine
from tests.unit.test_distill import ten_rows

pytestmark = pytest.mark.native


def test_model_ref_and_accepted_values_allow_null() -> None:
    files = to_dbt(fit_student(*ten_rows()), source="penguins", certificate=certificate())
    assert set(files) == {
        "models/answer_rule.sql",
        "models/schema.yml",
        "tests/answer_rule_coverage.sql",
    }
    assert files["models/answer_rule.sql"].endswith("FROM {{ ref('penguins') }}\n")
    schema = json.loads(files["models/schema.yml"])
    column = schema["models"][0]["columns"][0]
    assert column["name"] == "predicted_answer"
    assert column["data_tests"] == [
        {"accepted_values": {"arguments": {"values": ["a", "b"], "quote": True}}}
    ]
    assert COVERAGE_DRIFT_MARGIN == 0.10


@pytest.mark.parametrize(
    ("nulls", "total", "fails"),
    [(0, 0, False), (2, 10, False), (3, 10, False), (4, 10, True), (10, 10, True)],
)
def test_coverage_strict_boundary(nulls: int, total: int, *, fails: bool) -> None:
    files = to_dbt(fit_student(*ten_rows()), source="seed", certificate=certificate())
    sql = files["tests/answer_rule_coverage.sql"].replace("{{ ref('answer_rule') }}", "t")
    frame = pd.DataFrame({"predicted_answer": [None] * nulls + ["a"] * (total - nulls)})
    assert (len(engine("duckdb").execute(sql, frame)) == 1) is fails


@pytest.mark.parametrize("coverage", [Coverage(0, 0), Coverage(2, 1), Coverage(-1, 10)])
def test_coverage_requires_a_measured_baseline(coverage: Coverage) -> None:
    facts = replace(certificate(), in_sample=Count(0, 0, coverage))
    with pytest.raises(ValueError, match="positive total"):
        to_dbt(fit_student(*ten_rows()), source="seed", certificate=facts)


@pytest.mark.parametrize("name", ["../seed", "bad' }}", "two words", ""])
def test_dbt_resource_names_cannot_escape_refs_or_paths(name: str) -> None:
    with pytest.raises(UserError, match="dbt identifier"):
        to_dbt(fit_student(*ten_rows()), source=name, certificate=certificate())
    with pytest.raises(UserError, match="dbt identifier"):
        to_dbt(
            fit_student(*ten_rows()), source="seed", certificate=replace(certificate(), target=name)
        )
