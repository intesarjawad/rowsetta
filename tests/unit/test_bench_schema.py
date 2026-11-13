import importlib
import json

import pytest

from scripts.bench_common import BENCH_JSON, DOCUMENT, ROOT
from scripts.render_bench import active_svg, render

SCHEMA = ROOT / "docs/bench.schema.json"


def test_benchmark_document_matches_schema() -> None:
    validator = importlib.import_module("jsonschema")
    validator.validate(json.loads(BENCH_JSON.read_text()), json.loads(SCHEMA.read_text()))


@pytest.mark.parametrize("section", ["active", "active_noise", "distill", "leaks", "llm"])
def test_sections_require_provenance(section: str) -> None:
    validator = importlib.import_module("jsonschema")
    document = json.loads(BENCH_JSON.read_text())
    document[section] = {"results": []}
    with pytest.raises(validator.ValidationError):
        validator.validate(document, json.loads(SCHEMA.read_text()))


def test_markdown_and_chart_match_the_source() -> None:
    document = DOCUMENT.validate_json(BENCH_JSON.read_text())
    assert (ROOT / "docs/bench.md").read_text() == render(document)
    chart = ROOT / "docs/bench-data/active.svg"
    if chart.exists():
        assert chart.read_text() == active_svg(document)
