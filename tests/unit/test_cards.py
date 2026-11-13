from pathlib import Path

import pytest

CARDS = Path(__file__).resolve().parents[2] / "datasets" / "CARDS.md"


def card_licences(text: str) -> dict[str, str]:
    rows = [line for line in text.splitlines() if line.startswith("|")]
    assert rows, "CARDS.md must index its datasets and licences"
    cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]
    assert cells[0] == ["Dataset", "Files", "Licence"]
    assert all(len(row) == 3 for row in cells)
    datasets = cells[2:]
    assert datasets, "The card index must contain datasets"
    assert len({row[0] for row in datasets}) == len(datasets), "Duplicate dataset card"
    licences = {name: licence for name, _, licence in datasets}
    for name, licence in licences.items():
        assert licence in {"CC BY 4.0", "CC0"}, f"{name}: unsupported or missing licence"
    return licences


def test_every_dataset_has_an_allowed_licence_line() -> None:
    assert set(card_licences(CARDS.read_text())) == {
        "Palmer penguins",
        "Bank Marketing",
        "Adult",
        "Dry Bean",
        "Mushroom",
        "Car Evaluation",
    }


@pytest.mark.parametrize("licence", ["", "unknown", "CC BY-NC 4.0", "MIT", "CC BY 4.0 pending"])
def test_card_licence_validation_rejects_unapproved_or_missing_licences(licence: str) -> None:
    text = f"| Dataset | Files | Licence |\n| --- | --- | --- |\n| Example | data.csv | {licence} |"

    with pytest.raises(AssertionError, match="unsupported or missing licence"):
        card_licences(text)
