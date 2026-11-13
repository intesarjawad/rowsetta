"""Distilled rules and coverage-aware comparisons.

split_condition supplies the split literals to both tree_to_sql and
leaf_summary, so the rule view shows the same thresholds the SQL runs.
"""

import importlib
import shlex
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from math import sqrt
from typing import Literal, Protocol

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from rowsetta.core.evaluation import WILSON_Z
from rowsetta.core.features import DAY, EPOCH_DAYS, teacher_frame
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table
from rowsetta.core.teacher import Proposals

SEED = 7
CV_FOLDS = 5
ALPHA = 0.05
MIN_LEAF_ROWS = 5
LEAF_ROWS_DIVISOR = 100
BINARY_LEVELS = 2


class TreeStructure(Protocol):
    """Arrays shared by prediction, rule display and export."""

    children_left: NDArray[np.int64]
    children_right: NDArray[np.int64]
    feature: NDArray[np.int64]
    threshold: NDArray[np.float64]
    missing_go_to_left: NDArray[np.uint8]
    value: NDArray[np.float64]
    node_count: int


class TreeClassifier(Protocol):
    """The fitted scikit-learn tree surface needed by the pure core."""

    tree_: TreeStructure
    classes_: NDArray[np.str_]

    def fit(self, x: NDArray[np.float64], y: pd.Series) -> object:
        """Fit encoded features against source-indexed labels."""
        ...

    def apply(self, x: NDArray[np.float64]) -> NDArray[np.int64]:
        """Return a leaf node id for every row."""
        ...

    def get_depth(self) -> int:
        """Return the maximum fitted depth."""
        ...

    def get_n_leaves(self) -> int:
        """Return the fitted leaf count."""
        ...


@dataclass(frozen=True)
class Feature:
    """One tree input, retaining its source column for portable rules."""

    column: str
    kind: Literal["numeric", "datetime", "categorical"]
    value: str = ""

    @property
    def name(self) -> str:
        """Use col=value names only for one-hot inputs."""
        return f"{self.column}={self.value}" if self.kind == "categorical" else self.column


@dataclass(frozen=True)
class FeatureSpec:
    """Ordered tree inputs; missing and unseen categories both encode as zeros."""

    features: tuple[Feature, ...]

    def transform(self, frame: pd.DataFrame) -> NDArray[np.float64]:
        """Encode raw source rows without imputing missing numeric values."""
        matrix = np.empty((len(frame), len(self.features)), dtype=np.float64)
        for index, feature in enumerate(self.features):
            series = frame[feature.column]
            if feature.kind == "categorical":
                matrix[:, index] = (series.astype("string") == feature.value).to_numpy(
                    dtype=np.float64, na_value=0.0
                )
            else:
                if feature.kind == "datetime":
                    dates = pd.to_datetime(series, errors="coerce", format="mixed", utc=True)
                    series = (dates - EPOCH_DAYS) / DAY
                matrix[:, index] = series.to_numpy(dtype=np.float64, na_value=np.nan)
        return matrix


@dataclass(frozen=True)
class TreeSettings:
    """Resolved training parameters, including the training-set leaf floor."""

    max_depth: int = 4
    max_leaf_nodes: int = 16
    min_samples_leaf: int = MIN_LEAF_ROWS


@dataclass(frozen=True)
class Coverage:
    """Answered rows out of all eligible rows, independent of correctness."""

    answered: int
    total: int


@dataclass(frozen=True)
class Count:
    """Agreement among answered rows in a census, without an interval."""

    k: int
    n: int
    coverage: Coverage


@dataclass(frozen=True)
class Rate:
    """Agreement among answered rows with a 95% interval and coverage."""

    k: int
    n: int
    lo: float
    hi: float
    coverage: Coverage


@dataclass(frozen=True)
class Student:
    """A fitted rule and the source rows needed for local measurement."""

    tree: TreeClassifier
    feature_spec: FeatureSpec
    settings: TreeSettings
    leaf_purity: dict[int, float]
    threshold: float
    frame: pd.DataFrame
    teacher_labels: dict[int, str]
    eval_rows: frozenset[int]

    def predict(self, frame: pd.DataFrame) -> list[str | None]:
        """Abstain when the fitted leaf's purity is below the stored threshold."""
        if frame.empty:
            return []
        return [
            self.leaf_label(int(leaf))
            for leaf in self.tree.apply(self.feature_spec.transform(frame))
        ]

    def leaf_label(self, leaf: int) -> str | None:
        """Return the majority label, preserving abstention at this leaf."""
        if self.leaf_purity[leaf] < self.threshold:
            return None
        return str(self.tree.classes_[int(self.tree.tree_.value[leaf, 0].argmax())])


@dataclass(frozen=True)
class _FitData:
    frame: pd.DataFrame
    labels: dict[int, str]
    dates: frozenset[str]
    threshold: float
    eval_rows: frozenset[int]


def _fit(data: _FitData, settings: TreeSettings) -> Student:
    if not data.labels:
        message = "At least one non-evaluation teacher label is required to fit a rule."
        raise ValueError(message)
    training = data.frame.loc[list(data.labels)]
    features: list[Feature] = []
    for column in training.columns:
        if column in data.dates:
            features.append(Feature(column, "datetime"))
        elif pd.api.types.is_numeric_dtype(training[column].dtype):
            features.append(Feature(column, "numeric"))
        else:
            values = sorted(training[column].dropna().astype(str).unique())
            # Without missing values the second indicator of a two-level column is the first
            # one's mirror image. The tree sees an exact tie, which platforms break differently.
            mirrored = len(values) == BINARY_LEVELS and training[column].notna().all()
            features.extend(
                Feature(column, "categorical", value) for value in values[: 1 if mirrored else None]
            )
    if not features:
        message = "No usable training features remain. Include a numeric or categorical column."
        raise ValueError(message)
    spec = FeatureSpec(tuple(features))
    tree: TreeClassifier = importlib.import_module("sklearn.tree").DecisionTreeClassifier(
        max_depth=settings.max_depth,
        max_leaf_nodes=settings.max_leaf_nodes,
        min_samples_leaf=settings.min_samples_leaf,
        random_state=SEED,
    )
    tree.fit(spec.transform(training), pd.Series(data.labels))
    purity = {
        node: float(tree.tree_.value[node, 0].max() / tree.tree_.value[node, 0].sum())
        for node in range(tree.tree_.node_count)
        if tree.tree_.children_left[node] == -1
    }
    return Student(
        tree, spec, settings, purity, data.threshold, data.frame, data.labels, data.eval_rows
    )


def _teacher_labels(store: LabelStore, proposals: Proposals) -> dict[int, str]:
    labels = {
        row: label for row, label in proposals.label.items() if row not in proposals.abstained
    }
    labels.update(store.training_rows())
    return {
        row: labels[row]
        for row in store.source.row_ids()
        if row in labels and row not in store.eval_served
    }


def _fit_data(table: Table, store: LabelStore, labels: dict[int, str]) -> _FitData:
    columns = teacher_frame(table, store).frame.columns
    return _FitData(
        table.frame.loc[:, columns],
        labels,
        frozenset(column.name for column in table.columns if column.kind == "datetime"),
        store.threshold,
        frozenset(store.eval_served),
    )


def fit_student(
    table: Table,
    store: LabelStore,
    proposals: Proposals,
    *,
    max_depth: int = 4,
    max_leaf_nodes: int = 16,
) -> Student:
    """Distil human and answered teacher labels, reserving every evaluation row."""
    labels = _teacher_labels(store, proposals)
    settings = TreeSettings(
        max_depth, max_leaf_nodes, max(MIN_LEAF_ROWS, len(labels) // LEAF_ROWS_DIVISOR)
    )
    return _fit(_fit_data(table, store, labels), settings)


def _count(predicted: list[str | None], truth: list[str]) -> Count:
    answered = sum(label is not None for label in predicted)
    correct = sum(
        label == target for label, target in zip(predicted, truth, strict=True) if label is not None
    )
    return Count(correct, answered, Coverage(answered, len(truth)))


def fidelity_in_sample(student: Student, store: LabelStore, proposals: Proposals) -> Count:
    """Count agreement on eligible teacher labels, omitting abstaining rule leaves."""
    labels = _teacher_labels(store, proposals)
    return _count(student.predict(student.frame.loc[list(labels)]), list(labels.values()))


def clopper_pearson(count: Count) -> Rate:
    """Exact two-sided binomial bounds; no answers leave the full [0, 1] interval."""
    beta = importlib.import_module("scipy.stats").beta
    lo = float(beta.ppf(ALPHA / 2, count.k, count.n - count.k + 1)) if count.k else 0.0
    hi = (
        float(beta.ppf(1 - ALPHA / 2, count.k + 1, count.n - count.k)) if count.k < count.n else 1.0
    )
    return Rate(count.k, count.n, lo, hi, count.coverage)


def _wilson(count: Count) -> Rate:
    if not count.n:
        return Rate(0, 0, 0.0, 1.0, count.coverage)
    value = count.k / count.n
    squared = WILSON_Z**2
    denominator = 1 + squared / count.n
    center = (value + squared / (2 * count.n)) / denominator
    half_width = (
        WILSON_Z * sqrt(value * (1 - value) / count.n + squared / (4 * count.n**2)) / denominator
    )
    return Rate(
        count.k,
        count.n,
        max(0.0, center - half_width),
        min(1.0, center + half_width),
        count.coverage,
    )


def eval_accuracy(student: Student, store: LabelStore) -> Rate:
    """Measure answered evaluation rows with Wilson bounds as in teacher evaluation."""
    return _wilson(
        _count(student.predict(student.frame.loc[list(store.eval)]), list(store.eval.values()))
    )


def teacher_eval_accuracy(proposals: Proposals, store: LabelStore) -> Rate:
    """Measure conditional accuracy on confident predictions, with threshold coverage."""
    predicted = [None if row in proposals.abstained else proposals.label[row] for row in store.eval]
    return _wilson(_count(predicted, list(store.eval.values())))


def disagreements(student: Student, proposals: Proposals) -> list[int]:
    """Return source ids where both rule and teacher answer differently."""
    rows = [
        row
        for row in proposals.label
        if row not in proposals.abstained and row not in student.eval_rows
    ]
    predicted = student.predict(student.frame.loc[rows])
    return [
        row
        for row, label in zip(rows, predicted, strict=True)
        if label is not None and label != proposals.label[row]
    ]


class StratifiedSplitter(Protocol):
    """Source positions for disjoint training and validation folds."""

    def split(
        self, x: pd.DataFrame, y: pd.Series
    ) -> Iterator[tuple[NDArray[np.int64], NDArray[np.int64]]]:
        """Yield training and held-out row positions."""
        ...


def _folds(labels: dict[int, str], n: int) -> list[tuple[list[int], list[int]]]:
    splitter: StratifiedSplitter = importlib.import_module(
        "sklearn.model_selection"
    ).StratifiedKFold(n_splits=n, shuffle=True, random_state=SEED)
    series = pd.Series(labels)
    return [
        (list(series.iloc[train].index), list(series.iloc[test].index))
        for train, test in splitter.split(series.to_frame(), series)
    ]


class InsufficientFoldSupportError(ValueError):
    """Stratification needs more non-evaluation labels in specific classes."""

    def __init__(self, missing: dict[str, int], *, file_name: str) -> None:
        self.missing = missing
        self.what = "Insufficient class support for stratified cross-validation."
        needed = "; ".join(
            f"{count} more human labels for {label!r}" for label, count in missing.items()
        )
        self.next_step = (
            f"{shlex.join(['rowsetta', 'open', file_name])}; "
            f"add {needed} outside the evaluation set, then retry."
        )
        super().__init__(f"{self.what} Next: {self.next_step}")


def _require_fold_support(labels: dict[int, str], store: LabelStore, minimum: int) -> None:
    counts = Counter(labels.values())
    missing = {label: minimum - counts[label] for label in store.classes if counts[label] < minimum}
    if missing:
        raise InsufficientFoldSupportError(missing, file_name=store.source.file_name)


def fidelity_cross_fitted(student: Student, store: LabelStore, proposals: Proposals) -> Rate:
    """Refit preprocessing and rule on four folds before measuring the fifth."""
    labels = _teacher_labels(store, proposals)
    _require_fold_support(labels, store, CV_FOLDS)
    counts: list[Count] = []
    dates = frozenset(
        feature.column for feature in student.feature_spec.features if feature.kind == "datetime"
    )
    for train, test in _folds(labels, CV_FOLDS):
        data = _FitData(
            student.frame,
            {row: labels[row] for row in train},
            dates,
            student.threshold,
            student.eval_rows,
        )
        settings = TreeSettings(
            student.settings.max_depth,
            student.settings.max_leaf_nodes,
            max(MIN_LEAF_ROWS, len(train) // LEAF_ROWS_DIVISOR),
        )
        fitted = _fit(data, settings)
        counts.append(
            _count(fitted.predict(student.frame.loc[test]), [labels[row] for row in test])
        )
    answered = sum(count.n for count in counts)
    return clopper_pearson(
        Count(sum(count.k for count in counts), answered, Coverage(answered, len(labels)))
    )


@dataclass(frozen=True)
class DirectTree:
    """A human-only baseline with its answered evaluation accuracy."""

    student: Student
    accuracy: Rate


@dataclass(frozen=True)
class DirectTrees:
    """Fixed-setting and cross-validated human-only baselines."""

    same_settings: DirectTree
    tuned: DirectTree


def direct_trees(
    table: Table, store: LabelStore, *, settings: TreeSettings | None = None
) -> DirectTrees:
    """Fit human-only trees; pass student.settings to match a customized rule."""
    labels = {
        row: label for row, label in store.training_rows().items() if row not in store.eval_served
    }
    data = _fit_data(table, store, labels)
    if settings is None:
        settings = TreeSettings(
            min_samples_leaf=max(MIN_LEAF_ROWS, len(data.labels) // LEAF_ROWS_DIVISOR)
        )
    _require_fold_support(data.labels, store, 2)
    same = _fit(data, settings)
    folds = _folds(data.labels, min(CV_FOLDS, *Counter(data.labels.values()).values()))
    candidates: list[tuple[float, int, int, int, int, Student]] = []
    for depth in range(1, 7):
        for leaf_rows in (1, 2, 5):
            candidate_settings = TreeSettings(depth, 2**depth, leaf_rows)
            scores: list[float] = []
            for train, test in folds:
                training = _FitData(
                    data.frame,
                    {row: data.labels[row] for row in train},
                    data.dates,
                    0.0,
                    data.eval_rows,
                )
                fitted = _fit(training, candidate_settings)
                predicted = fitted.predict(data.frame.loc[test])
                truth = [data.labels[row] for row in test]
                recalls = [
                    sum(a == b for a, b in zip(predicted, truth, strict=True) if b == label)
                    / truth.count(label)
                    for label in sorted(set(truth))
                ]
                scores.append(sum(recalls) / len(recalls))
            candidate = _fit(data, candidate_settings)
            candidates.append(
                (
                    -sum(scores) / len(scores),
                    candidate.tree.get_n_leaves(),
                    candidate.tree.get_depth(),
                    depth,
                    -leaf_rows,
                    candidate,
                )
            )
    tuned = min(candidates, key=lambda item: item[:5])[-1]
    return DirectTrees(
        DirectTree(same, eval_accuracy(same, store)), DirectTree(tuned, eval_accuracy(tuned, store))
    )


@dataclass(frozen=True)
class RuleBetter:
    """Significant paired evidence in favour of the distilled rule."""

    p: float
    kind: Literal["rule_better"] = field(default="rule_better", init=False)


@dataclass(frozen=True)
class OtherBetter:
    """Significant paired evidence in favour of the comparison tree."""

    p: float
    kind: Literal["other_better"] = field(default="other_better", init=False)


@dataclass(frozen=True)
class NoDifference:
    """No significant difference over n jointly answered evaluation rows."""

    n: int
    kind: Literal["no_difference"] = field(default="no_difference", init=False)


type Comparison = RuleBetter | OtherBetter | NoDifference


def compare_on_eval(rule: Student, other: Student, store: LabelStore) -> Comparison:
    """Run exact, two-sided McNemar on evaluation pairs where both rules answer."""
    rows = list(store.eval)
    rule_predictions = rule.predict(rule.frame.loc[rows])
    other_predictions = other.predict(other.frame.loc[rows])
    rule_wins = other_wins = answered = 0
    for row, ours, theirs in zip(rows, rule_predictions, other_predictions, strict=True):
        if ours is None or theirs is None:
            continue
        answered += 1
        rule_wins += ours == store.eval[row] and theirs != store.eval[row]
        other_wins += theirs == store.eval[row] and ours != store.eval[row]
    discordant = rule_wins + other_wins
    if not discordant:
        return NoDifference(answered)
    p = float(
        importlib.import_module("scipy.stats")
        .binomtest(rule_wins, discordant, p=0.5, alternative="two-sided")
        .pvalue
    )
    if p >= ALPHA:
        return NoDifference(answered)
    return RuleBetter(p) if rule_wins > other_wins else OtherBetter(p)


@dataclass(frozen=True)
class LeafLine:
    """A root-to-leaf rule with source ids and answered teacher agreement."""

    line_no: int
    conditions: tuple[tuple[str, str, str], ...]
    label: str | None
    row_ids: list[int]
    agree: Count


def split_condition(
    feature: Feature, threshold: float, *, left: bool, missing_left: bool
) -> tuple[str, str, str]:
    """Return SQL-ready literals and operators, including missing-value routing.

    Numeric boundaries undo the tree's float32 input rounding. Compound operators
    use the source column for both the null test and comparison. Datetimes use
    the FeatureSpec epoch-day representation.
    """
    if feature.kind == "categorical":
        literal = "'" + feature.value.replace("'", "''") + "'"
        return feature.column, "IS NULL OR <>" if left else "=", literal
    if np.isposinf(threshold):
        return feature.column, "IS NOT NULL" if left else "IS NULL", ""
    lower = np.float32(threshold)
    if float(lower) > threshold:
        lower = np.nextafter(lower, np.float32(-np.inf))
    upper = np.nextafter(lower, np.float32(np.inf))
    midpoint = (float(lower) + float(upper)) / 2
    even = int(lower.view(np.uint32)) % 2 == 0
    op = ("<=" if even else "<") if left else (">" if even else ">=")
    op = ("IS NULL OR " if left == missing_left else "IS NOT NULL AND ") + op
    return feature.column, op, repr(midpoint)


def leaf_summary(student: Student, frame: pd.DataFrame) -> list[LeafLine]:
    """List every leaf left-to-right, retaining empty leaves and source row ids."""
    structure = student.tree.tree_
    leaves = (
        student.tree.apply(student.feature_spec.transform(frame))
        if len(frame)
        else np.empty(0, dtype=np.int64)
    )
    result: list[LeafLine] = []

    def visit(node: int, conditions: tuple[tuple[str, str, str], ...]) -> None:
        left_node = int(structure.children_left[node])
        if left_node == -1:
            rows = [int(row) for row in frame.index[leaves == node]]
            label = student.leaf_label(node)
            truth = [student.teacher_labels[row] for row in rows if row in student.teacher_labels]
            result.append(
                LeafLine(
                    len(result) + 1, conditions, label, rows, _count([label] * len(truth), truth)
                )
            )
            return
        feature = student.feature_spec.features[int(structure.feature[node])]
        for child, left in ((left_node, True), (int(structure.children_right[node]), False)):
            condition = split_condition(
                feature,
                float(structure.threshold[node]),
                left=left,
                missing_left=bool(structure.missing_go_to_left[node]),
            )
            visit(child, (*conditions, condition))

    visit(0, ())
    return result
