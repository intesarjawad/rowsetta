"""Open tree, preprocessing and certificate serialization."""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import TypeAdapter

from rowsetta.core.distill import FeatureSpec, Student, TreeSettings
from rowsetta.core.export.sql import Certificate


@dataclass(frozen=True)
class Leaf:
    """A terminal node with its unrounded purity and abstaining prediction."""

    node_id: int
    prediction: str | None
    purity: float
    kind: Literal["leaf"] = field(default="leaf", init=False)


@dataclass(frozen=True)
class Split:
    """A split evaluated after preprocessing and float32 input conversion."""

    node_id: int
    feature_index: int
    threshold: float
    missing_go_to_left: bool
    left: int
    right: int
    kind: Literal["split"] = field(default="split", init=False)


@dataclass(frozen=True)
class Tree:
    """Root node zero; child ids address the node array."""

    nodes: tuple[Leaf | Split, ...]
    classes: tuple[str, ...]
    input_dtype: Literal["float32"] = "float32"


@dataclass(frozen=True)
class Export:
    """Versioned rule document; missing categories encode as all-zero features."""

    tree: Tree
    preprocessing: FeatureSpec
    settings: TreeSettings
    abstention_threshold: float
    certificate: Certificate
    schema_sha256: str
    format_version: Literal[1] = 1


def to_json(student: Student, *, certificate: Certificate) -> str:
    """Serialize the fitted rule without source rows or teacher labels."""
    structure = student.tree.tree_
    nodes: list[Leaf | Split] = []
    for node in range(structure.node_count):
        left = int(structure.children_left[node])
        if left == -1:
            nodes.append(Leaf(node, student.leaf_label(node), student.leaf_purity[node]))
        else:
            nodes.append(
                Split(
                    node,
                    int(structure.feature[node]),
                    # The largest finite float32 routes every nonmissing input left.
                    min(float(structure.threshold[node]), float(np.finfo(np.float32).max)),
                    bool(structure.missing_go_to_left[node]),
                    left,
                    int(structure.children_right[node]),
                )
            )
    document = Export(
        Tree(tuple(nodes), tuple(str(label) for label in student.tree.classes_)),
        student.feature_spec,
        student.settings,
        student.threshold,
        certificate,
        certificate.schema_sha256,
    )
    return TypeAdapter(Export).dump_json(document, indent=2).decode() + "\n"
