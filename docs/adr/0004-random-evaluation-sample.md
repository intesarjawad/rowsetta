# 0004: Accuracy comes from a random, blind evaluation sample

Status: accepted.

## Decision

Accuracy is measured only on rows the app serves at random. Pressing `e`
serves the next row of a seeded permutation of the working sample
(`numpy.random.default_rng(eval_seed)`), skipping rows that already carry a
human label or have been served. The user labels that row without seeing a
proposal. Evaluation labels never train the teacher, never enter the rule
and never count as human labels.

## Why

Rows a person chooses to label are not a random sample: they are the rows the
active learner asked about, or the ones that looked easy or interesting.
Accuracy measured on them says little about the rows the rule will answer.
A served random sample is the one protocol that gives an unbiased estimate
whatever the labelling strategy, and it is the one an active-learning
researcher would accept.

## How it is enforced

- `LabelStore.set_eval` accepts only the currently served row; any other row
  raises `NotServedError` ("Press e and label the row shown").
- `LabelStore.set_human` refuses served rows, and the store validator rejects
  a session file whose human and evaluation rows overlap.
- The permutation is recreated from `eval_seed` on every call, so the order
  survives a saved and reloaded session.
- A unit test draws ten thousand seeded permutations and checks that every row
  is served first about equally often.
- Accuracy carries a Wilson interval from 20 served rows; balanced accuracy
  and per-class recall wait until each class has 5 served rows
  (`MIN_EVAL_ROWS` and `MIN_EVAL_PER_CLASS` in `core/evaluation.py`).

## Consequences

Evaluation costs labels that do not improve the model. The panel says how many
more rows each figure needs instead of showing a number it cannot support.
