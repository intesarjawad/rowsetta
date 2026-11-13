from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rowsetta.core.distill import Comparison, RuleBetter

DATASETS = ("penguins", "bank", "adult", "dry_bean", "mushroom", "car")
BUDGETS = (20, 50)
SEEDS = tuple(range(7, 17))
ARMS = ("random_tree", "al_tree")
SEEDS_REQUIRED = 5
DATASETS_REQUIRED = 3
SIGNIFICANCE = 0.05

type CellKey = tuple[str, int, int, str]


@dataclass(frozen=True)
class ArmComparison:
    """Held-out answered accuracy and the paired exact McNemar result."""

    rule_accuracy: float | None
    arm_accuracy: float | None
    verdict: Comparison

    @property
    def beats(self) -> bool:
        """Apply ADR 0006 without treating ties or missing answers as wins."""
        return (
            self.rule_accuracy is not None
            and self.arm_accuracy is not None
            and self.rule_accuracy > self.arm_accuracy
            and isinstance(self.verdict, RuleBetter)
            and self.verdict.p < SIGNIFICANCE
        )


@dataclass(frozen=True)
class RuleResult:
    """The frozen teacher-value decision and its supporting dataset names."""

    met: bool
    datasets_passing: tuple[str, ...]


def preregistered_rule(cells: Mapping[CellKey, ArmComparison | None]) -> RuleResult:
    """Require both arms in the same seed, at both budgets, on six datasets.

    A missing cell or an ineligible budget cannot establish a dataset pass.
    Extra budgets, noisy observations and unregistered seeds are not inputs.
    """
    passing: list[str] = []
    for dataset in DATASETS:
        budget_passes: list[bool] = []
        for budget in BUDGETS:
            wins = 0
            complete = True
            for seed in SEEDS:
                comparisons = [cells.get((dataset, budget, seed, arm)) for arm in ARMS]
                complete &= all(comparison is not None for comparison in comparisons)
                wins += all(
                    comparison is not None and comparison.beats for comparison in comparisons
                )
            budget_passes.append(complete and wins >= SEEDS_REQUIRED)
        if all(budget_passes):
            passing.append(dataset)
    return RuleResult(len(passing) >= DATASETS_REQUIRED, tuple(passing))


def completeness(
    cells: Mapping[CellKey, ArmComparison | None],
) -> Literal["complete", "incomplete"]:
    """Distinguish a partial smoke result from a completed scientific result."""
    return (
        "complete"
        if all(
            cells.get((dataset, budget, seed, arm)) is not None
            for dataset in DATASETS
            for budget in BUDGETS
            for seed in SEEDS
            for arm in ARMS
        )
        else "incomplete"
    )
