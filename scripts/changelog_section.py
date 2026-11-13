"""Print the CHANGELOG.md section for a release tag, as the GitHub release notes."""

import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def changelog_section(changelog: str, tag: str) -> str | None:
    """Return the body under `## [<version>]` for tag `v<version>`, or None if absent."""
    heading = f"## [{tag.removeprefix('v')}]"
    lines = changelog.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        return None
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip() + "\n"


def main() -> None:
    """Print the section for the tag given as the only argument; exit 1 when it is missing."""
    if len(sys.argv) != 2:  # noqa: PLR2004
        print("usage: changelog_section.py TAG", file=sys.stderr)
        raise SystemExit(2)
    tag = sys.argv[1]
    section = changelog_section(CHANGELOG.read_text(encoding="utf-8"), tag)
    if section is None:
        print(f"error: CHANGELOG.md has no section for {tag}", file=sys.stderr)
        print(
            f"Next: add a '## [{tag.removeprefix('v')}]' section, then tag again", file=sys.stderr
        )
        raise SystemExit(1)
    print(section, end="")


if __name__ == "__main__":
    main()
