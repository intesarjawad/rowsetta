import importlib
import importlib.abc
import multiprocessing
import sys
from collections.abc import Sequence
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import override

import numpy as np
import pandas as pd
import pytest

from rowsetta.core.distill import Feature, FeatureSpec, TreeClassifier
from rowsetta.core.export.sql import tree_to_sql
from tests.sql_support import engine, predictions

pytestmark = pytest.mark.native


class BlockTeachers(importlib.abc.MetaPathFinder):
    @override
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if fullname.startswith("rowsetta.teachers"):
            message = "Library export imported a teacher"
            raise AssertionError(message)
        return None


def _iris_export() -> None:
    assert not any(name.startswith("rowsetta.teachers") for name in sys.modules)
    sys.meta_path.insert(0, BlockTeachers())
    iris = importlib.import_module("sklearn.datasets").load_iris()
    frame = pd.DataFrame(iris.data, columns=iris.feature_names)
    frame.iloc[0, 0] = np.nan
    frame.iloc[51, 2] = np.nan
    tree: TreeClassifier = importlib.import_module("sklearn.tree").DecisionTreeClassifier(
        random_state=7
    )
    tree.fit(frame.to_numpy(), pd.Series(iris.target_names[iris.target]))
    spec = FeatureSpec(tuple(Feature(name, "numeric") for name in frame.columns))
    expected = [
        str(tree.classes_[int(tree.tree_.value[node, 0].argmax())])
        for node in tree.apply(spec.transform(frame))
    ]
    for dialect in ("duckdb", "sqlite"):
        sql = tree_to_sql(tree, feature_spec=spec, target="answer", dialect=dialect)
        assert predictions(engine(dialect).execute(sql, frame)) == expected
    assert not any(name.startswith("rowsetta.teachers") for name in sys.modules)


def test_iris_export_without_teacher_imports() -> None:
    process = multiprocessing.get_context("spawn").Process(target=_iris_export)
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("Library export did not finish within 60 seconds")
    assert process.exitcode == 0
