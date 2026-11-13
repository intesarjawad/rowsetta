import importlib
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from rowsetta.core import distill
from rowsetta.core.session import LabelStore, SourceRef
from rowsetta.core.table import Table, load_csv
from rowsetta.core.teacher import Proposals

DATASETS = Path(__file__).resolve().parents[2] / "src/rowsetta/datasets"


def labelled(frame: pd.DataFrame) -> tuple[Table, LabelStore, Proposals]:
    data = frame.to_csv(index=False).encode()
    table = load_csv(data)
    store = LabelStore(
        classes=tuple(sorted(str(value) for value in frame["answer"].unique())),
        target="answer",
        source=SourceRef.from_table("data.csv", data, table),
        human={row: str(value) for row, value in enumerate(frame["answer"])},
    )
    proposals = Proposals(store.human.copy(), {}, pd.DataFrame(), frozenset(), 0)
    return table, store, proposals


def ten_rows() -> tuple[Table, LabelStore, Proposals]:
    return labelled(pd.DataFrame({"x": [0] * 5 + [1] * 5, "answer": ["a"] * 7 + ["b"] * 3}))


def test_penguins_in_sample_agreement() -> None:
    frame = pd.read_csv(DATASETS / "penguins.csv").rename(columns={"species": "answer"})
    table, store, proposals = labelled(frame)
    student = distill.fit_student(table, store, proposals)
    count = distill.fidelity_in_sample(student, store, proposals)
    assert count.k / count.n >= 0.90
    assert count.coverage == distill.Coverage(344, 344)
    assert not hasattr(count, "lo")
    assert student.settings.min_samples_leaf == 5
    assert student.settings.max_depth == 4
    assert student.settings.max_leaf_nodes == 16


@pytest.mark.parametrize(("k", "lo", "hi"), [(0, 0, 0.168), (20, 0.832, 1)])
def test_clopper_pearson_reference(k: int, lo: float, hi: float) -> None:
    rate = distill.clopper_pearson(distill.Count(k, 20, distill.Coverage(20, 20)))
    assert (rate.k, rate.n) == (k, 20)
    assert round(rate.lo, 3) == lo
    assert round(rate.hi, 3) == hi


def test_abstaining_leaf_coverage_and_agreement() -> None:
    table, store, proposals = ten_rows()
    store.threshold = 0.8
    student = distill.fit_student(table, store, proposals, max_depth=1)
    assert student.predict(table.frame) == ["a"] * 5 + [None] * 5
    count = distill.fidelity_in_sample(student, store, proposals)
    assert count == distill.Count(5, 5, distill.Coverage(5, 10))
    assert sorted(student.leaf_purity.values()) == [0.6, 1.0]
    assert distill.disagreements(student, proposals) == []
    assert distill.disagreements(replace(student, threshold=0), proposals) == [5, 6]
    assert student.predict(table.frame.iloc[:0]) == []


def test_preprocessing_excludes_target_and_columns_and_zero_encodes_missing() -> None:
    frame = pd.DataFrame(
        {
            "x": [np.nan, 1.0] * 10,
            "cat": ["O'Reilly", None, "b", "b"] * 5,
            "excluded": range(20),
            "answer": ["a", "b"] * 10,
        }
    )
    table, store, proposals = labelled(frame)
    store.excluded_columns = frozenset({"excluded"})
    student = distill.fit_student(table, store, proposals)
    spec = student.feature_spec
    assert [feature.name for feature in spec.features] == ["x", "cat=O'Reilly", "cat=b"]
    matrix = spec.transform(table.frame)
    assert np.isnan(matrix[0, 0])
    np.testing.assert_array_equal(matrix[1, 1:], [0, 0])
    query = table.frame.iloc[[0]].assign(cat="unknown")
    np.testing.assert_array_equal(spec.transform(query)[0, 1:], [0, 0])
    assert "excluded" not in {feature.column for feature in spec.features}


def test_humans_override_proposals_and_eval_and_abstentions_are_excluded() -> None:
    table, store, proposals = ten_rows()
    store.human = {0: "a", 9: "b"}
    store.eval_served = [1, 2]
    store.eval = {1: "b"}
    proposals = replace(
        proposals, label={**proposals.label, 0: "b", 3: "unsure"}, abstained=frozenset({3})
    )
    student = distill.fit_student(table, store, proposals)
    count = distill.fidelity_in_sample(student, store, proposals)
    assert count.coverage.total == 7
    assert student.teacher_labels == {0: "a", 4: "a", 5: "a", 6: "a", 7: "b", 8: "b", 9: "b"}
    assert all(row not in distill.disagreements(student, proposals) for row in (1, 2, 3))


def test_zero_answered_rows_have_no_fabricated_agreement() -> None:
    table, store, proposals = ten_rows()
    student = replace(
        distill.fit_student(table, store, proposals), threshold=1.0, leaf_purity={1: 0.5, 2: 0.5}
    )
    count = distill.fidelity_in_sample(student, store, proposals)
    assert count == distill.Count(0, 0, distill.Coverage(0, 10))
    rate = distill.clopper_pearson(count)
    assert (rate.lo, rate.hi) == (0.0, 1.0)


def test_evaluation_includes_rule_and_teacher_coverage() -> None:
    table, store, proposals = ten_rows()
    student = replace(distill.fit_student(table, store, proposals), threshold=0.8)
    store.human = {}
    store.eval_served = list(range(10))
    store.eval = proposals.label.copy()
    rule = distill.eval_accuracy(student, store)
    assert rule.coverage == distill.Coverage(5, 10)
    assert (rule.k, rule.n) == (5, 5)
    proposals = replace(proposals, abstained=frozenset(range(5, 10)))
    teacher = distill.teacher_eval_accuracy(proposals, store)
    assert teacher.coverage == distill.Coverage(5, 10)
    assert (teacher.k, teacher.n) == (5, 5)


def test_cross_fitting_uses_only_other_folds_and_refits_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        {"x": range(50), "cat": [f"c{row}" for row in range(50)], "answer": ["a", "b"] * 25}
    )
    table, store, proposals = labelled(frame)
    table = replace(
        table,
        columns=tuple(
            replace(column, kind="categorical") if column.name == "cat" else column
            for column in table.columns
        ),
    )
    student = distill.fit_student(table, store, proposals)
    splits: list[tuple[set[int], set[int]]] = []
    selection = importlib.import_module("sklearn.model_selection")
    original_splitter = selection.StratifiedKFold
    trees = importlib.import_module("sklearn.tree")
    original_classifier = trees.DecisionTreeClassifier
    fits: list[set[int]] = []

    class SpySplitter:
        def __init__(self, *, n_splits: int, shuffle: bool, random_state: int) -> None:
            assert (n_splits, shuffle, random_state) == (5, True, 7)
            self.splitter: distill.StratifiedSplitter = original_splitter(
                n_splits=n_splits, shuffle=shuffle, random_state=random_state
            )

        def split(
            self, x: pd.DataFrame, y: pd.Series
        ) -> Iterator[tuple[NDArray[np.int64], NDArray[np.int64]]]:
            for train, test in self.splitter.split(x, y):
                splits.append((set(x.iloc[train].index), set(x.iloc[test].index)))
                yield train, test

    def spy_classifier(**kwargs: object) -> distill.TreeClassifier:
        estimator = original_classifier(**kwargs)
        original_fit = estimator.fit

        def spy_fit(x: NDArray[np.float64], y: pd.Series) -> object:
            fits.append(set(y.index))
            assert x.shape[1] == len(y) + 1
            return original_fit(x, y)

        estimator.fit = spy_fit
        return estimator

    monkeypatch.setattr(selection, "StratifiedKFold", SpySplitter)
    monkeypatch.setattr(trees, "DecisionTreeClassifier", spy_classifier)
    result = distill.fidelity_cross_fitted(student, store, proposals)
    assert len(fits) == len(splits) == 5
    for fitted_rows, (train, test) in zip(fits, splits, strict=True):
        assert fitted_rows == train
        assert fitted_rows.isdisjoint(test)
        assert train | test == set(range(50))
    assert {row for _, test in splits for row in test} == set(range(50))
    assert result.coverage == distill.Coverage(50, 50)
    assert result == distill.fidelity_cross_fitted(student, store, proposals)


def test_direct_trees_fit_only_humans_and_respect_custom_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame({"x": [0, 1] * 25, "answer": ["a", "b"] * 25})
    table, store, _ = labelled(frame)
    store.human = {row: label for row, label in store.human.items() if row < 20}
    store.eval_served = [20, 21, 22]
    store.eval = {20: "b", 21: "a"}
    trees = importlib.import_module("sklearn.tree")
    original_classifier = trees.DecisionTreeClassifier
    fitted_rows: list[set[int]] = []

    def spy_classifier(**kwargs: object) -> distill.TreeClassifier:
        estimator = original_classifier(**kwargs)
        original_fit = estimator.fit

        def spy_fit(x: NDArray[np.float64], y: pd.Series) -> object:
            fitted_rows.append(set(y.index))
            assert y.to_dict() == {row: store.human[row] for row in y.index}
            return original_fit(x, y)

        estimator.fit = spy_fit
        return estimator

    monkeypatch.setattr(trees, "DecisionTreeClassifier", spy_classifier)
    settings = distill.TreeSettings(max_depth=2, max_leaf_nodes=3, min_samples_leaf=5)
    result = distill.direct_trees(table, store, settings=settings)
    assert all(rows <= set(store.human) for rows in fitted_rows)
    assert {row for rows in fitted_rows for row in rows} == set(store.human)
    assert result.same_settings.student.settings == settings
    assert result.tuned.student.settings.max_depth == 1
    assert result.tuned.student.settings.min_samples_leaf == 5
    assert result.same_settings.accuracy.coverage == distill.Coverage(2, 2)
    assert result.tuned.accuracy.k == 0


@pytest.mark.parametrize(
    ("rule_wins", "other_wins", "verdict"),
    [
        (2, 1, distill.NoDifference),
        (9, 0, distill.RuleBetter),
        (0, 9, distill.OtherBetter),
        (0, 0, distill.NoDifference),
    ],
)
def test_exact_mcnemar(
    rule_wins: int,
    other_wins: int,
    verdict: type[distill.NoDifference | distill.RuleBetter | distill.OtherBetter],
) -> None:
    table, store, proposals = ten_rows()
    store.human = dict.fromkeys(range(10), "a")
    rule = distill.fit_student(table, store, proposals)
    store.human = dict.fromkeys(range(10), "b")
    other = distill.fit_student(table, store, proposals)
    store.human = {}
    store.eval_served = list(range(rule_wins + other_wins))
    store.eval = {row: "a" if row < rule_wins else "b" for row in store.eval_served}
    result = distill.compare_on_eval(rule, other, store)
    assert isinstance(result, verdict)
    if isinstance(result, distill.NoDifference):
        assert result.n == rule_wins + other_wins
    else:
        assert result.p == pytest.approx(0.00390625)
    abstaining = replace(other, threshold=1.0, leaf_purity={0: 0.5})
    assert distill.compare_on_eval(rule, abstaining, store) == distill.NoDifference(0)


@pytest.mark.parametrize("minimum", [0, 1, 4])
def test_cross_fidelity_rejects_insufficient_support(minimum: int) -> None:
    table, store, proposals = ten_rows()
    store.human = dict.fromkeys(range(5), "a")
    store.human.update(dict.fromkeys(range(5, 5 + minimum), "b"))
    proposals = replace(proposals, label=store.human.copy())
    student = distill.fit_student(table, store, proposals)
    with pytest.raises(distill.InsufficientFoldSupportError) as caught:
        distill.fidelity_cross_fitted(student, store, proposals)
    error = caught.value
    assert error.missing == {"b": 5 - minimum}
    assert error.next_step.startswith("rowsetta open data.csv;")
    assert f"{5 - minimum} more human labels for 'b'" in error.next_step
    assert error.next_step in str(error)


@pytest.mark.parametrize("humans", [{}, {0: "a"}, {0: "a", 1: "a", 7: "b"}])
def test_direct_trees_reject_insufficient_human_support(humans: dict[int, str]) -> None:
    table, store, _ = ten_rows()
    store.human = humans
    store.eval_served = [7]
    store.eval = {7: "b"}
    with pytest.raises(distill.InsufficientFoldSupportError) as caught:
        distill.direct_trees(table, store)
    assert caught.value.missing["b"] == 2
    assert "2 more human labels for 'b'" in str(caught.value)


def test_direct_trees_allow_two_folds() -> None:
    table, store, _ = ten_rows()
    store.human = {0: "a", 1: "a", 8: "b", 9: "b"}
    result = distill.direct_trees(table, store)
    assert result.tuned.student.teacher_labels == store.human


def test_cross_fidelity_fold_support_excludes_eval_and_abstained_labels() -> None:
    table, store, proposals = ten_rows()
    student = distill.fit_student(table, store, proposals)
    store.human = {0: "a"}
    store.eval_served = [9]
    proposals = replace(proposals, abstained=frozenset({8}))
    with pytest.raises(distill.InsufficientFoldSupportError) as caught:
        distill.fidelity_cross_fitted(student, store, proposals)
    assert caught.value.missing == {"b": 4}


class FourLeafTree:
    """Depth-two tree with a numeric root and categorical child splits."""

    def __init__(self) -> None:
        self.tree_: distill.TreeStructure = self
        self.children_left = np.array([1, 2, -1, -1, 5, -1, -1], dtype=np.int64)
        self.children_right = np.array([4, 3, -1, -1, 6, -1, -1], dtype=np.int64)
        self.feature = np.array([0, 1, -2, -2, 1, -2, -2], dtype=np.int64)
        self.threshold = np.array([0.5, 0.5, -2, -2, 0.5, -2, -2], dtype=np.float64)
        self.missing_go_to_left = np.array([1, 0, 0, 0, 0, 0, 0], dtype=np.uint8)
        self.value = np.array([[[1.0, 0.0]]] * 7)
        self.value[3, 0] = [0.6, 0.4]
        self.value[5, 0] = [0.0, 1.0]
        self.classes_ = np.array(["a", "b"])
        self.node_count = 7

    def fit(self, x: NDArray[np.float64], y: pd.Series) -> object:
        raise NotImplementedError

    def apply(self, x: NDArray[np.float64]) -> NDArray[np.int64]:
        result: list[int] = []
        for row in x.astype(np.float32):
            node = 0
            while self.children_left[node] != -1:
                value = row[self.feature[node]]
                left = (
                    bool(self.missing_go_to_left[node])
                    if np.isnan(value)
                    else value <= self.threshold[node]
                )
                node = int(self.children_left[node] if left else self.children_right[node])
            result.append(node)
        return np.array(result, dtype=np.int64)

    def get_depth(self) -> int:
        return 2

    def get_n_leaves(self) -> int:
        return 4


def test_leaf_summary_depth_two_literals_rows_abstention_and_agreement() -> None:
    frame = pd.DataFrame(
        {"x": [0.0, 0.0, 1.0, 1.0, np.nan], "cat": [None, "O'Reilly", "b", "O'Reilly", "b"]},
        index=[12, 9, 41, 2, 8],
    )
    student = distill.Student(
        FourLeafTree(),
        distill.FeatureSpec(
            (distill.Feature("x", "numeric"), distill.Feature("cat", "categorical", "O'Reilly"))
        ),
        distill.TreeSettings(),
        {2: 1.0, 3: 0.6, 5: 1.0, 6: 1.0},
        0.8,
        frame,
        {12: "a", 9: "a", 41: "a", 2: "a"},
        frozenset({8}),
    )
    lines = distill.leaf_summary(student, frame)
    assert [line.line_no for line in lines] == [1, 2, 3, 4]
    assert [line.row_ids for line in lines] == [[12, 8], [9], [41], [2]]
    assert [line.label for line in lines] == ["a", None, "b", "a"]
    assert [line.agree for line in lines] == [
        distill.Count(1, 1, distill.Coverage(1, 1)),
        distill.Count(0, 0, distill.Coverage(0, 1)),
        distill.Count(0, 1, distill.Coverage(1, 1)),
        distill.Count(1, 1, distill.Coverage(1, 1)),
    ]
    left = ("x", "IS NULL OR <=", "0.5000000298023224")
    right = ("x", "IS NOT NULL AND >", "0.5000000298023224")
    not_equal = ("cat", "IS NULL OR <>", "'O''Reilly'")
    equal = ("cat", "=", "'O''Reilly'")
    assert [line.conditions for line in lines] == [
        (left, not_equal),
        (left, equal),
        (right, not_equal),
        (right, equal),
    ]
    subset = distill.leaf_summary(student, frame.iloc[[3, 0]])
    assert [line.row_ids for line in subset] == [[12], [], [], [2]]
    empty = distill.leaf_summary(student, frame.iloc[:0])
    assert len(empty) == 4
    assert all(line.row_ids == [] and line.agree.coverage.total == 0 for line in empty)


@pytest.mark.parametrize("lower", [np.float32(0.5), np.nextafter(np.float32(0.5), np.float32(1))])
@pytest.mark.parametrize("missing_left", [False, True])
def test_split_condition_float32_midpoint_parity(lower: np.float32, *, missing_left: bool) -> None:
    upper = np.nextafter(lower, np.float32(np.inf))
    midpoint = (float(lower) + float(upper)) / 2
    even = int(lower.view(np.uint32)) % 2 == 0
    feature = distill.Feature("x", "numeric")
    for left in (True, False):
        column, op, literal = distill.split_condition(
            feature, float(lower), left=left, missing_left=missing_left
        )
        assert column == "x"
        assert float(literal) == midpoint
        assert op.startswith("IS NULL OR " if left == missing_left else "IS NOT NULL AND ")
        comparison = op.split()[-1]
        assert comparison == (("<=" if even else "<") if left else (">" if even else ">="))
        for value in (np.nextafter(midpoint, -np.inf), midpoint, np.nextafter(midpoint, np.inf)):
            expected = bool(np.float32(value) <= lower)
            actual = value <= midpoint if even else value < midpoint
            assert actual == expected


def test_split_condition_rounds_threshold_down_to_float32() -> None:
    lower = np.nextafter(np.float32(0.5), np.float32(1))
    upper = np.nextafter(lower, np.float32(1))
    threshold = (float(lower) + float(upper)) / 2
    assert np.float32(threshold) == upper
    assert distill.split_condition(
        distill.Feature("x", "numeric"), threshold, left=True, missing_left=False
    ) == ("x", "IS NOT NULL AND <", repr(threshold))


def test_leaf_summary_unsplit_tree_has_an_unconditional_line() -> None:
    table, store, proposals = ten_rows()
    store.human = dict.fromkeys(range(10), "a")
    student = distill.fit_student(table, store, proposals)
    assert distill.leaf_summary(student, table.frame) == [
        distill.LeafLine(
            1, (), "a", list(range(10)), distill.Count(10, 10, distill.Coverage(10, 10))
        )
    ]
