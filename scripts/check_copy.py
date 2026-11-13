"""Check public copy: emails, README numbers and prices."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
# Commands, versions and addresses are not claims about the product.
CODE_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
NOT_PROSE = re.compile(r"`[^`]*`|\]\([^)]*\)|<https?://[^>]*>|https?://\S+")
NUMBER = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?(?!\w|\.\d)(%?)")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PRICE = re.compile(r"\$\d")
OWNERSHIP = re.compile(r"\b(?:free|yours)\b", re.IGNORECASE)
# The licence line opens with the code licence, so its presence marks the line.
LICENCE_MARKER = "Apache-2.0"
SETUP_SECTIONS = ("install", "develop", "licence")
OWNERSHIP_SECTIONS = ("", "what you keep")
PERCENT = 100


@dataclass(frozen=True)
class Finding:
    """One line of public copy that breaks a rule."""

    line: int
    message: str


def check_prose(text: str) -> list[Finding]:
    """Flag email addresses."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), 1):
        if match := EMAIL.search(line):
            findings.append(Finding(number, f"email address {match.group(0)!r}"))
    return findings


def sections(text: str) -> Iterator[tuple[str, list[tuple[int, str]]]]:
    """Yield each `## ` section's lowercase title and numbered lines; the hero has title ''."""
    title, lines = "", list[tuple[int, str]]()
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            yield title, lines
            title, lines = line[3:].strip().lower(), []
        lines.append((number, line))
    yield title, lines


def matches_bench(token: str, percent: str, bench: tuple[float, ...]) -> bool:
    """Accept a number when a benchmark value rounds to it at the precision shown."""
    value = float(token.replace(",", ""))
    places = len(token.partition(".")[2])
    if percent:
        value, places = value / PERCENT, places + 2
    return any(round(measured, places) == value for measured in bench)


def check_readme(text: str, bench: tuple[float, ...]) -> list[Finding]:
    """Trace README numbers to the benchmark and keep prices and ownership words honest."""
    findings = check_prose(text)
    blanked = CODE_FENCE.sub(lambda fence: "\n" * fence.group(0).count("\n"), text)
    for title, lines in sections(blanked):
        body = "\n".join(line for _, line in lines)
        if title in OWNERSHIP_SECTIONS and OWNERSHIP.search(body) and LICENCE_MARKER not in body:
            findings.append(
                Finding(lines[0][0], f"'free' or 'yours' without the {LICENCE_MARKER} licence line")
            )
        if title.startswith(SETUP_SECTIONS):
            continue
        for number, line in lines:
            prose = NOT_PROSE.sub(" ", line)
            if LICENCE_MARKER in line:
                continue
            if PRICE.search(prose):
                if not (DATE.search(line) and "https://" in line):
                    findings.append(Finding(number, "price without a YYYY-MM-DD date and source"))
                continue
            findings.extend(
                Finding(number, f"number {match.group(0)} is not in docs/bench.json")
                for match in NUMBER.finditer(prose)
                if not matches_bench(match.group(0).rstrip("%"), match.group(1), bench)
            )
    return findings


def bench_numbers(document: JsonValue) -> Iterator[float]:
    """Walk the benchmark document and yield every numeric value."""
    if isinstance(document, dict):
        for value in document.values():
            yield from bench_numbers(value)
    elif isinstance(document, list):
        for value in document:
            yield from bench_numbers(value)
    elif isinstance(document, (int, float)) and not isinstance(document, bool):
        yield float(document)


def check(root: Path) -> list[str]:
    """Check the README, the docs and the issue and pull request templates."""
    document = TypeAdapter(JsonValue).validate_json((root / "docs/bench.json").read_bytes())
    bench = tuple(bench_numbers(document))
    github = root / ".github"
    paths = [
        *sorted((root / "docs").rglob("*.md")),
        *sorted((github / "ISSUE_TEMPLATE").glob("*")),
        github / "PULL_REQUEST_TEMPLATE.md",
    ]
    results = [
        (root / "README.md", check_readme((root / "README.md").read_text(encoding="utf-8"), bench)),
        *((path, check_prose(path.read_text(encoding="utf-8"))) for path in paths if path.exists()),
    ]
    return [
        f"{path.relative_to(root)}:{finding.line}: {finding.message}"
        for path, findings in results
        for finding in findings
    ]


def main() -> None:
    """Print every finding; exit 1 when there is one."""
    findings = check(ROOT)
    for finding in findings:
        print(finding)
    if findings:
        print("Next: rewrite those lines, then run uv run python scripts/check_copy.py")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
