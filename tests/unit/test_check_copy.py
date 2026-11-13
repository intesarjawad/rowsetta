from pathlib import Path

import pytest

from scripts.check_copy import check, check_prose, check_readme

ROOT = Path(__file__).resolve().parents[2]
BENCH_NUMBERS = (0.9137, 344, 0.0512)


def test_email_address_flags_the_line() -> None:
    findings = check_prose("# Title\n\nWrite to someone@example.com.\n")
    assert [finding.line for finding in findings] == [3]


def test_plain_prose_passes() -> None:
    assert check_prose("# Title\n\nA rule you can read, with a measured error.\n") == []


def test_readme_numbers_must_come_from_the_benchmark() -> None:
    readme = "# Title\n\nAccuracy 91.4% on 344 rows, 3 minutes.\n"
    findings = check_readme(readme, BENCH_NUMBERS)
    assert [(finding.line, "3" in finding.message) for finding in findings] == [(3, True)]


def test_numbers_in_code_links_and_setup_sections_are_not_claims() -> None:
    readme = (
        "# Title\n\nRun `uvx rowsetta@0.1.0 demo --port 8787` "
        "or see <http://127.0.0.1:5173> and [ADR](docs/adr/0002.md).\n\n"
        "```sh\nsleep 30\n```\n\n## Install\n\nNeeds Node 26.\n\n"
        "## Licence\n\nCC BY 4.0 data.\n"
    )
    assert check_readme(readme, BENCH_NUMBERS) == []


@pytest.mark.parametrize(
    ("line", "flagged"),
    [
        ("Prodigy costs $490 per seat.", True),
        ("Prodigy costs $490 per seat (2026-11-04, https://prodi.gy/buy).", False),
    ],
)
def test_prices_carry_a_date_and_a_source(line: str, *, flagged: bool) -> None:
    findings = check_readme(f"# Title\n\n{line}\n", BENCH_NUMBERS)
    assert bool(findings) == flagged


@pytest.mark.parametrize(
    ("readme", "flagged"),
    [
        ("# Title\n\nFree to run.\n", True),
        ("# Title\n\nFree to run. Apache-2.0 code, BSD-3 weights.\n", False),
        ("# Title\n\n## What you keep\n\nThe SQL is yours.\n", True),
        ("# Title\n\n## Why\n\nThe SQL is yours.\n", False),
    ],
)
def test_ownership_words_need_the_licence_line(readme: str, *, flagged: bool) -> None:
    assert bool(check_readme(readme, BENCH_NUMBERS)) == flagged


def test_repository_passes() -> None:
    assert check(ROOT) == []
