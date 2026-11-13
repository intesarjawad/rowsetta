from dataclasses import replace

import pytest

from rowsetta.core.distill import NoDifference, OtherBetter, RuleBetter
from rowsetta.core.prereg import (
    ARMS,
    BUDGETS,
    DATASETS,
    SEEDS,
    ArmComparison,
    CellKey,
    completeness,
    preregistered_rule,
)


def cells_with_winners(datasets: int, seeds: int = 5) -> dict[CellKey, ArmComparison | None]:
    return {
        (dataset, budget, seed, arm): ArmComparison(
            0.9,
            0.7,
            RuleBetter(0.01) if index < datasets and seed_index < seeds else NoDifference(100),
        )
        for index, dataset in enumerate(DATASETS)
        for budget in BUDGETS
        for seed_index, seed in enumerate(SEEDS)
        for arm in ARMS
    }


@pytest.mark.parametrize(("datasets", "met"), [(3, True), (2, False)])
def test_three_of_six_datasets(datasets: int, *, met: bool) -> None:
    result = preregistered_rule(cells_with_winners(datasets))
    assert result.met is met
    assert result.datasets_passing == DATASETS[:datasets]


@pytest.mark.parametrize(("seeds", "met"), [(5, True), (4, False)])
def test_five_of_ten_seeds(seeds: int, *, met: bool) -> None:
    assert preregistered_rule(cells_with_winners(3, seeds)).met is met


@pytest.mark.parametrize(
    "comparison",
    [
        ArmComparison(0.9, 0.7, NoDifference(100)),
        ArmComparison(0.9, 0.9, RuleBetter(0.01)),
        ArmComparison(0.6, 0.7, RuleBetter(0.01)),
        ArmComparison(None, 0.7, RuleBetter(0.01)),
        ArmComparison(0.9, None, RuleBetter(0.01)),
        ArmComparison(0.9, 0.7, RuleBetter(0.05)),
        ArmComparison(0.9, 0.7, OtherBetter(0.01)),
    ],
)
def test_point_estimate_alone_never_wins(comparison: ArmComparison) -> None:
    cells = cells_with_winners(3)
    cells[(DATASETS[0], 20, SEEDS[0], ARMS[0])] = comparison
    assert not preregistered_rule(cells).met


def test_winning_seeds_must_beat_both_arms_together() -> None:
    cells = cells_with_winners(3, 10)
    for index, seed in enumerate(SEEDS):
        arm = ARMS[index // 5]
        key = (DATASETS[0], 20, seed, arm)
        comparison = cells[key]
        assert comparison is not None
        cells[key] = replace(comparison, verdict=NoDifference(100))
    assert not preregistered_rule(cells).met


@pytest.mark.parametrize("missing", [False, True])
def test_both_budgets_required(*, missing: bool) -> None:
    cells = cells_with_winners(3)
    for seed in SEEDS:
        for arm in ARMS:
            cells[(DATASETS[0], 50, seed, arm)] = (
                None if missing else ArmComparison(0.9, 0.7, NoDifference(100))
            )
    assert not preregistered_rule(cells).met


def test_na_budget_and_partial_seed_set_fail() -> None:
    cells = cells_with_winners(3)
    cells[(DATASETS[0], 20, SEEDS[-1], ARMS[0])] = None
    assert not preregistered_rule(cells).met
    assert completeness(cells) == "incomplete"
    assert completeness(cells_with_winners(3)) == "complete"
    assert not preregistered_rule({}).met


def test_entire_budget_twenty_unavailable_cannot_pass() -> None:
    cells = cells_with_winners(3)
    for seed in SEEDS:
        for arm in ARMS:
            cells[(DATASETS[0], 20, seed, arm)] = None
    assert not preregistered_rule(cells).met
