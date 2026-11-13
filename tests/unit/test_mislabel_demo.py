import pandas as pd

from scripts.mislabel_demo import DATASET, TARGET, mislabel


def test_changes_nine_labels_to_another_class_the_same_way_every_run() -> None:
    original = pd.read_csv(DATASET)
    first, second = original.copy(), original.copy()

    rows = mislabel(first)

    assert rows == mislabel(second)
    assert len(rows) == 9
    before = original[TARGET].astype(str)
    after = first[TARGET].astype(str)
    assert (after[rows] != before[rows]).all()
    unchanged = original.drop(index=rows)
    assert first.drop(index=rows).equals(unchanged)
