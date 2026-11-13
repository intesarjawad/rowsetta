"""Write the penguins demo with nine species labels changed, for the label audit screenshots.

The changed rows and their new labels come from a fixed seed, so every run writes
the same file: `uv run python scripts/mislabel_demo.py /tmp/penguins-mislabelled.csv`,
then `uv run rowsetta open /tmp/penguins-mislabelled.csv` and pick `species`.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATASET = Path(__file__).resolve().parents[1] / "src" / "rowsetta" / "datasets" / "penguins.csv"
TARGET = "species"
CHANGED = 9
SEED = 7


def mislabel(frame: pd.DataFrame, *, changed: int = CHANGED, seed: int = SEED) -> list[int]:
    """Give `changed` labelled rows another class, in place; return their row ids."""
    labelled = frame[TARGET].dropna().astype(str)
    classes = sorted(labelled.unique())
    rng = np.random.default_rng(seed)
    rows = sorted(int(row) for row in rng.choice(labelled.index.to_list(), changed, replace=False))
    for row in rows:
        frame.loc[row, TARGET] = str(rng.choice([c for c in classes if c != labelled[row]]))
    return rows


def main() -> None:
    """Write the changed table to the one path given."""
    match sys.argv[1:]:
        case [output]:
            frame = pd.read_csv(DATASET)
            rows = mislabel(frame)
            frame.to_csv(output, index=False)
            print(f"wrote {output}; changed rows {rows}")
        case _:
            sys.exit("usage: mislabel_demo.py OUTPUT.csv")


if __name__ == "__main__":
    main()
