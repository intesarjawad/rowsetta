import json
from pathlib import Path

import numpy as np
import pandas as pd

from rowsetta.core.leaks import find_leaks
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import load_csv

ROOT = Path(__file__).resolve().parents[2]


def test_bank_near_copy_golden() -> None:
    bank = pd.read_csv(ROOT / "src/rowsetta/datasets/bank.csv")
    rng = np.random.default_rng(7)
    bank["y_after"] = bank["y"].copy()
    flipped = rng.choice(len(bank), size=round(0.03 * len(bank)), replace=False)
    bank.loc[flipped, "y_after"] = bank.loc[flipped, "y_after"].map({"yes": "no", "no": "yes"})
    data = bank.to_csv(index=False).encode()
    table = load_csv(data)
    labels = json.loads((ROOT / "tests/fixtures/bank_labels.json").read_text())
    store = LabelStore(
        target="y",
        classes=("no", "yes"),
        source=SourceRef.from_table("bank.csv", data, table),
        human=labels,
    )
    hints = find_leaks(table, store)
    assert {(hint.column, hint.kind) for hint in hints} == {
        ("y_after", "single-column"),
        ("y_after", "name"),
    }
    score = next(hint.score for hint in hints if hint.kind == "single-column")
    assert score is not None
    assert score >= 0.95
