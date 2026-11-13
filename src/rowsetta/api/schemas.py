from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rowsetta.core.session import MAX_CLASSES, MIN_CLASSES


class InputModel(BaseModel):
    """Reject unknown fields at the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DemoInput(InputModel):
    """Select the bundled offline demo."""

    demo: Literal["penguins"]


class TargetInput(InputModel):
    """Declare a target with its classes, or omit them to take classes and labels from a column."""

    target: str = Field(min_length=1)
    classes: tuple[str, ...] = Field(default=(), max_length=MAX_CLASSES)

    @model_validator(mode="after")
    def distinct_classes(self) -> Self:
        """Reject ambiguous or empty class names before replacing the session."""
        if self.classes and len(self.classes) < MIN_CLASSES:
            message = f"Name at least {MIN_CLASSES} classes, or none to take them from the column."
            raise ValueError(message)
        if len(set(self.classes)) != len(self.classes) or any(not name for name in self.classes):
            message = "Classes must be distinct, nonempty names."
            raise ValueError(message)
        return self


class LabelInput(InputModel):
    """Set or clear one answer in the selected labelling mode."""

    label: str | None
    mode: Literal["human", "eval"] = "human"


class ExclusionInput(InputModel):
    """Whether a source feature is omitted from teacher and rule fitting."""

    excluded: bool


class ThresholdInput(InputModel):
    """Minimum probability or leaf purity required for an answer."""

    threshold: float = Field(ge=0, le=1, allow_inf_nan=False)


class DistillInput(InputModel):
    """Select the maximum depth for the distilled rule."""

    max_depth: int = Field(default=4, ge=1)


class OutputModel(BaseModel):
    """A response body; reads core dataclasses by attribute so routes need not copy fields."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


class ErrorBody(OutputModel):
    """The recovery fields every failure carries, here as a refit failure inside the state."""

    error: str
    next_step: str
    missing: dict[str, int] = Field(default_factory=dict, exclude_if=lambda missing: not missing)


class Measured(OutputModel):
    """A measured proportion with its 95% interval."""

    kind: Literal["measured"]
    value: float
    lo: float
    hi: float


class NeedsRows(OutputModel):
    """Evaluation rows per class while a measurement is withheld."""

    kind: Literal["needs_rows"]
    counts: dict[str, int]


class Evaluation(OutputModel):
    """Accuracy on blind evaluation rows against the majority-class baseline."""

    n: int
    accuracy: Measured
    balanced_accuracy: Annotated[Measured | NeedsRows, Field(discriminator="kind")]
    per_class_recall: dict[str, float | None]
    majority_class: str
    majority_baseline: float


class WorkspaceState(OutputModel):
    """Labels, proposals and measurements, with reserved evaluation predictions removed."""

    loaded: bool
    file_name: str | None = None
    notice: str | None
    target: str | None
    classes: list[str]
    human: dict[int, str]
    eval_count: int
    threshold: float
    excluded_columns: list[str]
    generation: int
    refit_generation: int | None
    proposals: dict[int, str]
    confidence: dict[int, float]
    abstained: list[int]
    missing: dict[str, int]
    next_row: int | None
    evaluation: Evaluation | None
    failure: ErrorBody | None
    dev_states: bool


class ColumnInfo(OutputModel):
    """A source column's inferred kind and ratios."""

    name: str
    kind: Literal["numeric", "categorical", "text", "datetime"]
    distinct_ratio: float
    missing_ratio: float


# `int` is listed so integer cells are not sent as `39.0`.
type Cell = str | int | float | bool | None


class TablePage(OutputModel):
    """One page of source rows; the target column is always null."""

    rows: list[dict[str, Cell]]
    row_ids: list[int]
    columns: list[ColumnInfo]
    total: int
    source_rows: int
    page: int
    size: int


class EvalNext(OutputModel):
    """The next blind evaluation row, or null once every row has been served."""

    row_id: int | None


class Coverage(OutputModel):
    """Answered rows out of all eligible rows."""

    answered: int
    total: int


class Agreement(OutputModel):
    """Rows where the rule agrees with the teacher, among answered rows."""

    k: int
    n: int
    coverage: Coverage


class LeafLine(OutputModel):
    """One root-to-leaf rule line with the source rows it covers."""

    line_no: int
    conditions: list[tuple[str, str, str]]
    label: str | None
    row_ids: list[int]
    agree: Agreement


class Distilled(OutputModel):
    """The distilled rule as display lines, for the inputs of one generation.

    `disagreements` lists the rows where the rule and the teacher both answer, differently.
    """

    leaf_summary: list[LeafLine]
    disagreements: list[int]
    generation: int


class LeakHint(OutputModel):
    """A column that may give the answer away."""

    column: str
    kind: Literal["identifier", "single-column", "name"]
    reason: str
    score: float | None


class Audit(OutputModel):
    """Columns that may leak the answer."""

    leaks: list[LeakHint]


class Suspect(OutputModel):
    """A human label and the out-of-fold teacher probability of that label."""

    row_id: int
    given: str
    given_probability: float
    likely: str


class Suspects(OutputModel):
    """Human labels from least to most plausible."""

    suspects: list[Suspect]


class Health(OutputModel):
    """The unauthenticated liveness probe; it carries no workspace state."""

    ok: bool
