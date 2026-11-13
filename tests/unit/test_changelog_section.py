import subprocess
import sys
from pathlib import Path

import pytest

from scripts.changelog_section import changelog_section

CHANGELOG = """# Changelog

## [Unreleased]

- Pending.

## [0.2.0] - 2026-12-01

### Added

- Parquet input.

## [0.1.0] - 2026-11-20

- First release.
"""
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "changelog_section.py"


def test_returns_only_the_tagged_section() -> None:
    assert changelog_section(CHANGELOG, "v0.2.0") == "### Added\n\n- Parquet input.\n"
    assert changelog_section(CHANGELOG, "v0.1.0") == "- First release.\n"


def test_a_tag_without_a_section_gives_none() -> None:
    assert changelog_section(CHANGELOG, "v0.3.0") is None
    assert changelog_section(CHANGELOG, "v0.1") is None


@pytest.mark.native
def test_the_command_exits_1_with_the_next_step_for_a_missing_section() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "v99.0.0"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "error: CHANGELOG.md has no section for v99.0.0",
        "Next: add a '## [99.0.0]' section, then tag again",
    ]
