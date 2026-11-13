import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import html
import json

from pydantic import JsonValue

from scripts.bench_common import BENCH_JSON, DOCUMENT, ROOT, Section


def display(value: JsonValue) -> str:
    """Render nested metric counts without losing coverage or precision in the source."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, dict):
        return "; ".join(f"{key}={display(item)}" for key, item in sorted(value.items()))
    if isinstance(value, list):
        return ", ".join(display(item) for item in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def render(document: dict[str, JsonValue]) -> str:
    """Produce byte-identical evidence tables from identical machine-readable input."""
    lines = [
        "# Benchmark measurements",
        "",
        "Generated from [bench.json](bench.json).",
        "",
        (
            "Accuracy is among answered rows. Coverage is reported separately. "
            "Bootstrap intervals resample seeds with seed 7."
        ),
        "",
    ]
    for name, value in sorted(document.items()):
        lines.extend([f"## {name.replace('_', ' ').title()}", ""])
        if not isinstance(value, dict) or "script" not in value:
            lines.extend(["```json", json.dumps(value, indent=2, sort_keys=True), "```", ""])
            continue
        section = Section.model_validate(value)
        lines.extend(
            [
                (
                    f"Script: `{section.script}`. Revision: `{section.git_sha}`. "
                    f"Machine: {section.machine}. Wall seconds: {section.wall_seconds:.6f}."
                ),
                "",
                f"Settings: {display(section.settings)}.",
                "",
            ]
        )
        if "preregistered_rule" in value:
            lines.extend(
                [
                    f"Pre-registered result: {display(value['preregistered_rule'])}.",
                    "",
                    (
                        "An incomplete matrix is provisional and cannot establish "
                        "the final teacher-value verdict."
                    ),
                    "",
                ]
            )
        if value.get("ineligible_cells"):
            lines.extend([display(value["ineligible_cells"]), ""])
        table_rows = value.get("summaries", section.results)
        if not isinstance(table_rows, list):
            message = "Benchmark summaries must be a list"
            raise TypeError(message)
        for result in table_rows:
            if not isinstance(result, dict):
                message = "Benchmark table rows must be objects"
                raise TypeError(message)
            lines.extend(["| Measurement | Value |", "| --- | --- |"])
            for key, measurement in sorted(result.items()):
                lines.append(f"| {key} | {display(measurement)} |")
            lines.append("")
    active = document.get("active")
    if isinstance(active, dict):
        lines.extend(
            ["## Label efficiency", "", "![Accuracy by label budget](bench-data/active.svg)", ""]
        )
    return "\n".join(lines)


def active_svg(document: dict[str, JsonValue]) -> str:
    """Plot accuracy and confidence intervals in separate labelled dataset panels."""
    active = document.get("active")
    if not isinstance(active, dict):
        return '<svg xmlns="http://www.w3.org/2000/svg"/>\n'
    section = Section.model_validate(active)
    datasets = sorted({str(row["dataset"]) for row in section.results})
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{len(datasets) * 320}" '
            f'viewBox="0 0 900 {len(datasets) * 320}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for panel, dataset in enumerate(datasets):
        origin = panel * 320
        parts.append(
            f'<text x="60" y="{origin + 20}" font-family="sans-serif" font-size="16">'
            f"{html.escape(dataset)}: held-out accuracy, 95% bootstrap bands</text>"
        )
        parts.append(
            f'<path d="M60 {origin + 40} V{origin + 270} H650" fill="none" stroke="black"/>'
        )
        groups: dict[str, list[tuple[int, dict[str, JsonValue]]]] = {}
        for row in section.results:
            metric = row.get("accuracy")
            budget = row.get("budget")
            if row["dataset"] == dataset and isinstance(metric, dict) and isinstance(budget, int):
                groups.setdefault(f"{row['learner']}/{row['strategy']}", []).append(
                    (budget, metric)
                )
        for index, (label, points) in enumerate(sorted(groups.items())):
            hue = index * 360 / max(1, len(groups))
            coordinates: list[str] = []
            for budget, metric in sorted(points):
                mean, lo, hi = (metric[key] for key in ("mean", "lo", "hi"))
                if not all(isinstance(item, (int, float)) for item in (mean, lo, hi)):
                    continue
                x = 60 + budget / 200 * 580
                y = origin + 270 - float(str(mean)) * 230
                coordinates.append(f"{x:.3f},{y:.3f}")
                parts.append(
                    f'<path d="M{x:.3f} {origin + 270 - float(str(lo)) * 230:.3f} '
                    f'V{origin + 270 - float(str(hi)) * 230:.3f}" '
                    f'stroke="hsl({hue},60%,35%)"/>'
                )
            parts.append(
                f'<polyline points="{" ".join(coordinates)}" fill="none" '
                f'stroke="hsl({hue},60%,35%)"/>'
            )
            parts.append(
                f'<text x="660" y="{origin + 40 + index * 14}" '
                f'font-family="sans-serif" font-size="10" fill="hsl({hue},60%,35%)">'
                f"{html.escape(label)}</text>"
            )
        parts.extend(
            f'<text x="{60 + budget / 200 * 580}" y="{origin + 290}" font-size="10">{budget}</text>'
            for budget in (10, 20, 50, 100, 200)
        )
        parts.extend(
            f'<text x="20" y="{origin + 270 - accuracy * 230}" font-size="10">{accuracy}</text>'
            for accuracy in (0.0, 0.5, 1.0)
        )
        parts.append(f'<text x="290" y="{origin + 310}" font-size="12">Human labels</text>')
    return "\n".join([*parts, "</svg>", ""])


def main() -> None:
    """Regenerate Markdown and SVG without a model or network connection."""
    document = DOCUMENT.validate_json(BENCH_JSON.read_text())
    (ROOT / "docs/bench.md").write_text(render(document))
    destination = ROOT / "docs/bench-data/active.svg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(active_svg(document))
    print("Rendered docs/bench.md and docs/bench-data/active.svg")


if __name__ == "__main__":
    main()
