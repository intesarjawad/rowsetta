import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import asdict
from time import perf_counter

import numpy as np
from pydantic import BaseModel, JsonValue

from rowsetta.core import distill
from rowsetta.core.prereg import (
    ARMS,
    ArmComparison,
    CellKey,
    completeness,
    preregistered_rule,
)
from rowsetta.core.teacher import proposals_from_proba
from scripts.bench_active import Acquisition, run_trajectory, scores
from scripts.bench_common import (
    Observation,
    atomic_json,
    band,
    checkpoint_path,
    count_json,
    load_checkpoint,
    matrix,
    parser,
    provenance,
    publish,
    session,
)
from scripts.bench_identity import identity


class DistilledCell(BaseModel):
    """One complete rule and all its paired comparisons, saved before aggregation."""

    dataset: str
    budget: int
    seed: int
    wall_seconds: float
    results: dict[str, JsonValue]
    comparisons: dict[str, dict[str, JsonValue]]


def comparison_json(comparison: distill.Comparison) -> dict[str, JsonValue]:
    """Retain the exact p-value and decision kind without rounding."""
    return dict(asdict(comparison))


def measure(observation: Observation, baselines: list[Observation]) -> DistilledCell:
    """Fit the frozen rule and baselines without exposing held-out labels to training."""
    start = perf_counter()
    table, store = session(observation.dataset, observation.seed)
    store.human = observation.human.copy()
    proposals = proposals_from_proba(
        np.array(observation.proba), observation.classes, store, generation=0
    )
    student = distill.fit_student(table, store, proposals)
    direct = distill.direct_trees(table, store, settings=student.settings)
    truth = list(store.eval.values())
    rule_scores = scores(truth, student.predict(table.frame.loc[list(store.eval)]))
    results: dict[str, JsonValue] = {
        "rule": rule_scores,
        "teacher": scores(
            truth,
            [
                proposals.label[row] if row not in proposals.abstained else None
                for row in store.eval
            ],
        ),
        "teacher_wilson": count_json(distill.teacher_eval_accuracy(proposals, store)),
        "sql_identity": identity(student, store.target),
    }
    comparisons: dict[str, dict[str, JsonValue]] = {}
    students = {"same_settings": direct.same_settings.student, "tuned": direct.tuned.student}
    for baseline in baselines:
        arm_store = store.model_copy(deep=True)
        arm_store.human = baseline.human.copy()
        students["random_tree" if baseline.strategy == "random" else "al_tree"] = (
            distill.direct_trees(table, arm_store).tuned.student
        )
    for arm, other in students.items():
        results[arm] = scores(truth, other.predict(table.frame.loc[list(store.eval)]))
        comparisons[arm] = comparison_json(distill.compare_on_eval(student, other, store))
    depths: list[JsonValue] = []
    for depth in range(2, 7):
        rule = distill.fit_student(table, store, proposals, max_depth=depth)
        entry: dict[str, JsonValue] = {
            "depth": depth,
            "in_sample": count_json(distill.fidelity_in_sample(rule, store, proposals)),
            "evaluation": count_json(distill.eval_accuracy(rule, store)),
        }
        try:
            entry["cross_fitted"] = count_json(
                distill.fidelity_cross_fitted(rule, store, proposals)
            )
        except distill.InsufficientFoldSupportError as error:
            entry["cross_fitted"] = {"status": f"unavailable: {error}"}
        depths.append(entry)
    results["depths"] = depths
    return DistilledCell(
        dataset=observation.dataset,
        budget=observation.budget,
        seed=observation.seed,
        wall_seconds=perf_counter() - start,
        results=results,
        comparisons=comparisons,
    )


def rule_inputs(cells: list[DistilledCell]) -> dict[CellKey, ArmComparison | None]:
    """Reconstruct typed comparisons for the pure pre-registered decision function."""
    inputs: dict[CellKey, ArmComparison | None] = {}
    for cell in cells:
        rule = cell.results["rule"]
        if not isinstance(rule, dict):
            message = "Rule metrics must be an object."
            raise TypeError(message)
        for arm in ARMS:
            other = cell.results[arm]
            if not isinstance(other, dict):
                message = "Arm metrics must be an object."
                raise TypeError(message)
            comparison = cell.comparisons[arm]
            p = comparison.get("p")
            verdict: distill.Comparison = distill.NoDifference(0)
            if isinstance(p, (int, float)):
                verdict = (
                    distill.RuleBetter(p)
                    if comparison["kind"] == "rule_better"
                    else distill.OtherBetter(p)
                )
            ours, theirs = rule["accuracy"], other["accuracy"]
            inputs[(cell.dataset, cell.budget, cell.seed, arm)] = ArmComparison(
                float(ours) if isinstance(ours, (int, float)) else None,
                float(theirs) if isinstance(theirs, (int, float)) else None,
                verdict,
            )
    return inputs


def summaries(cells: list[DistilledCell]) -> list[JsonValue]:
    """Report accuracy bands and McNemar verdict shares over independent seeds."""
    groups: dict[tuple[str, int], list[DistilledCell]] = {}
    for cell in cells:
        groups.setdefault((cell.dataset, cell.budget), []).append(cell)
    results: list[JsonValue] = []
    for (dataset, budget), group in sorted(groups.items()):
        entry: dict[str, JsonValue] = {"dataset": dataset, "budget": budget, "seeds": len(group)}
        for arm in ("rule", "teacher", "same_settings", "tuned", "random_tree", "al_tree"):
            accuracies: list[float] = []
            coverage: list[float] = []
            for cell in group:
                metric = cell.results[arm]
                if isinstance(metric, dict):
                    accuracy, answered, total = (
                        metric["accuracy"],
                        metric["answered"],
                        metric["total"],
                    )
                    if isinstance(accuracy, (int, float)):
                        accuracies.append(float(accuracy))
                    if isinstance(answered, int) and isinstance(total, int):
                        coverage.append(answered / total)
            entry[arm] = {
                "accuracy": band(accuracies) if accuracies else None,
                "coverage": band(coverage) if coverage else None,
            }
            if arm not in ("rule", "teacher"):
                entry[arm + "_mcnemar_share"] = {
                    kind: sum(cell.comparisons[arm]["kind"] == kind for cell in group) / len(group)
                    for kind in ("rule_better", "other_better", "no_difference")
                }
        results.append(entry)
    return results


def main() -> None:
    """Measure distilled rules and compute ADR 0006 solely from cached cell results."""
    args = parser("Resumable rule and no-teacher benchmark").parse_args()
    datasets, budgets, seeds = matrix(args)
    start = perf_counter()
    section = provenance(
        "scripts/bench_distill.py",
        0,
        {
            "smoke": args.smoke,
            "datasets": datasets,
            "budgets": budgets,
            "seeds": seeds,
            "oracle_noise": 0.0,
        },
    )
    cells: list[DistilledCell] = []
    for name in datasets:
        for seed in seeds:
            ours = run_trajectory(name, budgets, Acquisition(seed, "tabicl", "ours"))
            random = run_trajectory(name, budgets, Acquisition(seed, "tree", "random"))
            active = run_trajectory(name, budgets, Acquisition(seed, "tree", "ours"))
            for observation, random_arm, active_arm in zip(ours, random, active, strict=True):
                path = checkpoint_path(
                    "distill",
                    {
                        "dataset": name,
                        "source_sha256": observation.source_sha256,
                        "seed": seed,
                        "budget": observation.budget,
                    },
                )
                cell = load_checkpoint(path, DistilledCell)
                if cell is None:
                    cell = measure(observation, [random_arm, active_arm])
                    atomic_json(path, cell.model_dump(mode="json"))
                    print(
                        f"distill {name} budget={cell.budget} seed={seed} "
                        f"seconds={cell.wall_seconds:.3f}",
                        flush=True,
                    )
                cells.append(cell)
                section.results = [item.model_dump(mode="json") for item in cells]
                section.wall_seconds = perf_counter() - start
                inputs = rule_inputs(cells)
                result = preregistered_rule(inputs)
                publish(
                    "distill",
                    section,
                    summaries=summaries(cells),
                    preregistered_rule={
                        "met": result.met and completeness(inputs) == "complete",
                        "datasets_passing": list(result.datasets_passing),
                        "status": completeness(inputs),
                    },
                )
    print(f"distill complete cells={len(cells)} wall_seconds={perf_counter() - start:.3f}")


if __name__ == "__main__":
    main()
