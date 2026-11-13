from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from rowsetta.core.features import teacher_frame
from rowsetta.core.lite_teacher import LiteTeacher
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import load_csv

if TYPE_CHECKING:
    from rowsetta.core.teacher import Teacher


def test_lite_is_deterministic_with_categories_missing_and_unseen_values() -> None:
    x = pd.DataFrame({"number": [1.0, np.nan, 8.0, 9.0], "category": ["a", None, "b", "b"]})
    y = pd.Series(["a", "a", "b", "b"])
    first: Teacher = LiteTeacher()
    second: Teacher = LiteTeacher()
    first.fit(x, y)
    second.fit(x, y)
    test = pd.DataFrame({"number": [np.nan, 9.0], "category": ["unseen", "b"]})
    assert first.classes == ("a", "b")
    np.testing.assert_array_equal(first.predict_proba(test), second.predict_proba(test))
    np.testing.assert_allclose(first.predict_proba(test).sum(axis=1), 1)


def test_six_labels_beat_penguins_majority() -> None:
    path = Path(__file__).resolve().parents[2] / "src/rowsetta/datasets/penguins.csv"
    data = path.read_bytes()
    table = load_csv(data)
    labels = table.frame["species"].astype(str)
    classes = tuple(sorted(labels.unique()))
    store = LabelStore(
        target="species", classes=classes, source=SourceRef.from_table(path.name, data, table)
    )
    frame = teacher_frame(table, store).frame
    rng = np.random.default_rng(7)
    chosen = [
        int(row)
        for label in classes
        for row in rng.choice(
            frame.index[(labels == label) & frame.notna().all(axis=1)], 2, replace=False
        )
    ]
    teacher = LiteTeacher()
    teacher.fit(frame.loc[chosen], labels.loc[chosen])
    remaining = frame.index.difference(chosen)
    actual = np.array(teacher.classes)[teacher.predict_proba(frame.loc[remaining]).argmax(axis=1)]
    accuracy = float((actual == labels.loc[remaining]).mean())
    baseline = float(labels.loc[remaining].value_counts(normalize=True).max())
    assert accuracy > baseline
