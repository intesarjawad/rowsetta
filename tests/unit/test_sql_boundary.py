import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rowsetta.core.distill import Feature, FeatureSpec
from rowsetta.core.export.sql import Dialect, SqlOptions, tree_to_sql
from tests.sql_support import engine, predictions
from tests.unit.test_distill import FourLeafTree

pytestmark = pytest.mark.native
DIALECTS = ["duckdb", "sqlite", pytest.param("postgres", marks=pytest.mark.pg)]
FLOAT32_LIMIT = float(np.float32(1e30))
THRESHOLDS = st.lists(
    st.floats(min_value=-FLOAT32_LIMIT, max_value=FLOAT32_LIMIT, width=32),
    min_size=3,
    max_size=3,
)


@pytest.mark.parametrize("dialect", DIALECTS)
@settings(max_examples=60, deadline=None, derandomize=True)
@given(
    thresholds=THRESHOLDS,
    missing=st.lists(st.booleans(), min_size=3, max_size=3),
    labels=st.lists(st.sampled_from([None, "a", "b", "O'Reilly"]), min_size=4, max_size=4),
    threshold_is_midpoint=st.booleans(),
)
def test_float32_boundaries_match_tree(
    dialect: Dialect,
    thresholds: list[float],
    missing: list[bool],
    labels: list[str | None],
    *,
    threshold_is_midpoint: bool,
) -> None:
    tree = FourLeafTree()
    spec = FeatureSpec((Feature("x", "numeric"), Feature("y", "numeric")))
    values = [np.nan, -1e30, 1e30, -0.0, 0.0]
    for node, threshold, missing_left in zip((0, 1, 4), thresholds, missing, strict=True):
        lower = np.float32(threshold)
        upper = np.nextafter(lower, np.float32(np.inf))
        midpoint = (float(lower) + float(upper)) / 2
        tree.threshold[node] = midpoint if threshold_is_midpoint else threshold
        tree.missing_go_to_left[node] = missing_left
        values.extend(
            (
                midpoint,
                np.nextafter(midpoint, -np.inf),
                np.nextafter(midpoint, np.inf),
                float(lower),
                float(upper),
                float(np.nextafter(lower, np.float32(-np.inf))),
            )
        )
    frame = pd.DataFrame({"x": values * 2, "y": values + list(reversed(values))})
    nodes = tree.apply(spec.transform(frame))
    by_node: dict[int, str | None] = dict(zip((2, 3, 5, 6), labels, strict=True))
    expected = [by_node[int(node)] for node in nodes]
    sql = tree_to_sql(
        tree,
        feature_spec=spec,
        target="answer",
        dialect=dialect,
        options=SqlOptions(leaf_labels=labels),
    )
    result = engine(dialect).execute(sql, frame)
    assert predictions(result) == expected
    assert result["predicted_answer_confidence"].tolist() == [
        round(float(tree.value[node, 0].max() / tree.value[node, 0].sum()), 4) for node in nodes
    ]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("missing_left", [True, False])
@pytest.mark.parametrize("odd", [True, False])
def test_even_and_odd_midpoint_ties(dialect: Dialect, *, missing_left: bool, odd: bool) -> None:
    tree = FourLeafTree()
    lower = np.float32(0.5)
    if odd:
        lower = np.nextafter(lower, np.float32(np.inf))
    upper = np.nextafter(lower, np.float32(np.inf))
    midpoint = (float(lower) + float(upper)) / 2
    tree.threshold[0] = float(lower)
    tree.missing_go_to_left[0] = missing_left
    frame = pd.DataFrame(
        {
            "x": [
                np.nextafter(midpoint, -np.inf),
                midpoint,
                np.nextafter(midpoint, np.inf),
                np.nan,
            ],
            "cat": [None] * 4,
        }
    )
    spec = FeatureSpec((Feature("x", "numeric"), Feature("cat", "categorical", "yes")))
    sql = tree_to_sql(
        tree,
        feature_spec=spec,
        target="answer",
        dialect=dialect,
        options=SqlOptions(leaf_labels=["left", "left", "right", "right"]),
    )
    assert predictions(engine(dialect).execute(sql, frame)) == [
        "left",
        "right" if odd else "left",
        "right",
        "left" if missing_left else "right",
    ]
