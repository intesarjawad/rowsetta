# 0006: Pre-registered teacher-value rule

Status: accepted on 2026-11-05, before the first full benchmark run (`make
bench-full`). The rule and its thresholds are frozen.

## Decision

This rule was committed before the first full benchmark run. Its thresholds
cannot change after that run. `core/prereg.py` implements it and
`tests/unit/test_preregistered_rule.py` tests it.

For one dataset, budget and seed, the distilled rule beats an arm when its
held-out accuracy is higher and the exact McNemar test on the paired held-out
rows gives `RuleBetter` (two-sided, p < 0.05).

A dataset passes when, at budget 20 and at budget 50, the rule beats both
no-teacher arms in at least 5 of 10 seeds. The arms are a tuned tree fitted on
the same number of randomly chosen labels (`random_tree`) and a tuned tree that
chose its own labels by active learning (`al_tree`). The teacher-value rule is met
when at least 3 of the 6 datasets pass.

## Consequences

If the rule is not met, I will choose either to reposition the product
around live fill, the blind evaluation protocol and the certificate, with copy
saying the rule matches a tuned tree, or to pursue a different project.
