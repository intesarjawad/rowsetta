# Exporting any scikit-learn tree to SQL

`tree_to_sql` turns a fitted scikit-learn `DecisionTreeClassifier` into one
`SELECT` statement for DuckDB, PostgreSQL or SQLite. It needs no model, no web
app and no PyTorch: the app's own exports are built on the same function.

```python
from importlib.resources import files

import duckdb
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from rowsetta.core.distill import Feature, FeatureSpec
from rowsetta.core.export.sql import SqlOptions, tree_to_sql

penguins = pd.read_csv(files("rowsetta.datasets") / "penguins.csv")
spec = FeatureSpec(
    (
        Feature("flipper_length_mm", "numeric"),
        Feature("island", "categorical", "Dream"),
    )
)
tree = DecisionTreeClassifier(max_depth=3, random_state=7)
tree.fit(spec.transform(penguins), penguins["species"])
sql = tree_to_sql(
    tree,
    feature_spec=spec,
    target="species",
    dialect="duckdb",
    options=SqlOptions(table_name="penguins"),
)
print(duckdb.sql(sql).df().head())
```

The query returns every source column plus `predicted_<target>` and
`predicted_<target>_confidence`, the share of the leaf's training rows in its
majority class.

## The feature spec

The tree sees a matrix; the SQL sees your table. `FeatureSpec` is the bridge,
one `Feature` per tree input in column order:

- `Feature("age", "numeric")` reads the column as it is. Keep source columns
  in float64 or an integer type; a `REAL` column has already lost the
  precision the boundaries rely on.
- `Feature("island", "categorical", "Dream")` is the one-hot input
  `island=Dream`. The SQL compares the original string column, so a value the
  tree never saw goes down the "not Dream" side, as it does in
  `FeatureSpec.transform`.

Fit the tree on `spec.transform(frame)` so the matrix and the SQL agree on
column order and encoding.

## What the SQL guarantees

- **Float32 boundaries.** scikit-learn compares float32 inputs with float64
  thresholds. Each split is printed as the exact float64 midpoint between the
  two float32 neighbours of the threshold, so a value on the boundary lands in
  the same leaf in SQL as in `tree.apply`. [ADR 0008](adr/0008-sql-float32-boundaries.md)
  has the rule.
- **Missing values.** A SQL `NULL` follows the tree's own missing-value routing
  (`missing_go_to_left`), so a tree fitted on data with gaps keeps its answers.
- **Three engines.** The test suite executes the SQL on DuckDB, SQLite and
  PostgreSQL and compares every row with `tree.apply`.

## Options

`SqlOptions` holds what most callers leave alone:

- `table_name`, the table the query reads (default `t`);
- `leaf_labels`, one label per leaf in left-to-right order, overriding the
  majority class; `None` for a leaf makes it answer `NULL`, which is how the
  app's rule abstains;
- `certificate`, the comment header the app writes above its exports.

Datetime splits raise `UnsupportedDatetimeSplitError`: there is no portable
SQL for them across the three engines.
