import importlib
from typing import Protocol

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from rowsetta.core.distill import direct_trees
from rowsetta.core.features import teacher_frame
from rowsetta.core.lite_teacher import LiteTeacher
from rowsetta.core.session import LabelStore
from rowsetta.core.table import Table
from rowsetta.teachers.tabicl import TabICLTeacher

LEARNERS = ("tabicl", "tabpfn", "forest", "lite", "logistic", "label_spreading", "self_training")
STRATEGIES = ("ours", "random", "margin")
FOREST_TREES = 300


class Classifier(Protocol):
    """The integer-label probability interface shared by benchmark classifiers."""

    classes_: NDArray[np.int64]
    label_distributions_: NDArray[np.float64]

    def fit(self, x: NDArray[np.float64], y: NDArray[np.int64]) -> object:
        """Fit encoded labels; semi-supervised models accept -1 for unknown rows."""
        ...

    def predict_proba(self, x: NDArray[np.float64]) -> NDArray[np.float64]:
        """Return class probabilities in classes_ order."""
        ...


def probabilities(name: str, table: Table, store: LabelStore, seed: int) -> NDArray[np.float64]:
    """Fit one learner using only human answers and its allowed unlabelled features."""
    frame = teacher_frame(table, store).frame
    rows = list(store.human)
    if name == "tree":
        student = direct_trees(table, store).tuned.student
        leaves = student.tree.apply(student.feature_spec.transform(frame))
        return np.asarray(student.tree.tree_.value[leaves, 0], dtype=np.float64)
    if name in ("tabicl", "lite"):
        teacher = TabICLTeacher() if name == "tabicl" else LiteTeacher()
        teacher.fit(frame.loc[rows], pd.Series(store.human).loc[rows])
        predictions = teacher.predict_proba(frame)
        return predictions[:, [teacher.classes.index(label) for label in store.classes]]
    classifier: Classifier
    if name == "tabpfn":
        module = importlib.import_module("tabpfn")
        constants = importlib.import_module("tabpfn.constants")
        classifier = module.TabPFNClassifier.create_default_for_version(
            constants.ModelVersion.V2, device="cpu", random_state=seed
        )
    elif name == "forest":
        classifier = importlib.import_module("sklearn.ensemble").RandomForestClassifier(
            n_estimators=FOREST_TREES, random_state=seed
        )
    elif name == "logistic":
        classifier = importlib.import_module("sklearn.linear_model").LogisticRegression(C=1.0)
    elif name == "label_spreading":
        classifier = importlib.import_module("sklearn.semi_supervised").LabelSpreading(
            kernel="knn", n_neighbors=7
        )
    elif name == "self_training":
        forest = importlib.import_module("sklearn.ensemble").RandomForestClassifier(
            n_estimators=FOREST_TREES, random_state=seed
        )
        classifier = importlib.import_module("sklearn.semi_supervised").SelfTrainingClassifier(
            estimator=forest, threshold=0.9
        )
    else:
        message = f"Unknown benchmark learner: {name}"
        raise ValueError(message)
    matrix = pd.get_dummies(frame, dtype=float).fillna(0).to_numpy(dtype=np.float64)
    positions = [list(frame.index).index(row) for row in rows]
    labels = np.array([store.classes.index(store.human[row]) for row in rows], dtype=np.int64)
    scaler = importlib.import_module("sklearn.preprocessing").StandardScaler()
    scaler.fit(matrix if name == "label_spreading" else matrix[positions])
    matrix = np.asarray(scaler.transform(matrix), dtype=np.float64)
    if name in ("label_spreading", "self_training"):
        targets = np.full(len(frame), -1, dtype=np.int64)
        targets[positions] = labels
        fit_positions = (
            list(range(len(frame)))
            if name == "label_spreading"
            else [i for i, row in enumerate(frame.index) if row not in store.eval]
        )
        classifier.fit(matrix[fit_positions], targets[fit_positions])
    else:
        classifier.fit(matrix[positions], labels)
    proba = (
        classifier.label_distributions_
        if name == "label_spreading"
        else classifier.predict_proba(matrix)
    )
    proba = np.asarray(proba[:, np.argsort(classifier.classes_)], dtype=np.float64)
    # Disconnected graph components have no labelled neighbours; retain uncertainty.
    empty = proba.sum(axis=1) == 0
    proba[empty] = 1 / len(store.classes)
    return proba
