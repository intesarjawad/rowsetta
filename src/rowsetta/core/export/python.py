"""Standalone Python prediction using the shared float32 split boundaries."""

from rowsetta.core.distill import Student, split_condition
from rowsetta.core.export.sql import ONE_HOT_THRESHOLD, UnsupportedDatetimeSplitError


def to_python(student: Student) -> str:
    """Render a dependency-free predictor for numeric and categorical source cells.

    Missing cells are None or float NaN. Numeric values retain float64 precision;
    split literals account for the tree's float32 input rounding.
    """
    structure = student.tree.tree_

    def visit(node: int, depth: int) -> list[str]:
        indent = "    " * depth
        left = int(structure.children_left[node])
        if left == -1:
            return [f"{indent}return {student.leaf_label(node)!r}"]
        feature = student.feature_spec.features[int(structure.feature[node])]
        if feature.kind == "datetime":
            raise UnsupportedDatetimeSplitError(feature.column)
        value = f"row[{feature.column!r}]"
        missing = f"({value} is None or (isinstance({value}, float) and isnan({value})))"
        if feature.kind == "categorical":
            if structure.threshold[node] != ONE_HOT_THRESHOLD:
                message = "Categorical features must be one-hot encoded with a 0.5 split."
                raise ValueError(message)
            condition = f"{missing} or str({value}) != {feature.value!r}"
        else:
            _, operator, literal = split_condition(
                feature,
                float(structure.threshold[node]),
                left=True,
                missing_left=bool(structure.missing_go_to_left[node]),
            )
            if operator in ("IS NULL", "IS NOT NULL"):
                condition = missing if operator == "IS NULL" else f"not {missing}"
            else:
                comparison = f"{value} {operator.split()[-1]} {literal}"
                condition = (
                    f"{missing} or {comparison}"
                    if structure.missing_go_to_left[node]
                    else f"not {missing} and {comparison}"
                )
        return [
            f"{indent}if {condition}:",
            *visit(left, depth + 1),
            f"{indent}else:",
            *visit(int(structure.children_right[node]), depth + 1),
        ]

    return "\n".join(
        [
            "from math import isnan",
            "",
            "",
            "def predict(row: dict[str, object]) -> str | None:",
            *visit(0, 1),
            "",
        ]
    )
