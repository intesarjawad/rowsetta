from pathlib import Path

import pandas as pd

PENGUINS = Path(__file__).resolve().parents[1] / "src/rowsetta/datasets/penguins.csv"
LABEL_ROWS = 20
SMOKE_ROWS = 10
SEED = 7


def penguins_split() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the same disjoint, complete penguins rows for both smoke probes."""
    frame = pd.read_csv(PENGUINS).dropna().sample(frac=1, random_state=SEED)
    return frame.iloc[:LABEL_ROWS], frame.iloc[LABEL_ROWS : LABEL_ROWS + SMOKE_ROWS]
