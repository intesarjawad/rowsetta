"""Write bank_leak.csv: the bundled bank table plus `y_after`, an outcome recorded after the call.

`y_after` restates `y` in other words, the textbook post-outcome leak the leak list must catch.
Run once from the repository root: `uv run python tests/fixtures/make_bank_leak.py`.
"""

import csv
from pathlib import Path

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src/rowsetta/datasets/bank.csv"
OUTPUT = Path(__file__).with_name("bank_leak.csv")
AFTER_CALL = {"yes": "deposit opened", "no": "no deposit"}


def main() -> None:
    with SOURCE.open(newline="", encoding="utf-8") as source:
        rows = list(csv.reader(source))
    header, body = rows[0], rows[1:]
    outcome = header.index("y")
    with OUTPUT.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([*header, "y_after"])
        writer.writerows([*row, AFTER_CALL[row[outcome]]] for row in body)


if __name__ == "__main__":
    main()
