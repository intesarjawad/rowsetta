# 0008: SQL boundaries and supported feature types

Status: accepted.

scikit-learn casts tree inputs to float32 before comparing them with a float64
threshold. Comparing the original SQL value directly with that threshold can
send boundary rows to the wrong leaf.

For each numeric split, find the largest float32 `g` not above the threshold
and its next float32 neighbour `h`. Emit the exact float64 midpoint
`m = (g + h) / 2`, printed with `repr(float(m))`. Use `<= m` when `g` has an
even significand and `< m` otherwise, preserving round-half-to-even ties.
The shared `split_condition` function supplies these literals to both SQL and
leaf summaries. Source numeric columns must retain float64 precision. Missing
cells are SQL NULL and follow the tree's `missing_go_to_left` routing.

Confidence values retain four decimal places. PostgreSQL casts the complete
confidence expression to `DOUBLE PRECISION`, including an unsplit tree's leaf
literal, so the result is a float rather than PostgreSQL's default `NUMERIC`
type for decimal literals.

The exporter supports numeric and one-hot categorical splits. A used datetime split
raises `UnsupportedDatetimeSplitError`, names its column, and supplies a
command-first recovery step to exclude the column and re-teach without it.
Unused datetime features do not block export. There is no datetime parsing
that behaves the same on DuckDB, PostgreSQL and SQLite, so none is emitted.

`tree_to_sql` groups optional table naming, leaf labels and certificate facts
in frozen `SqlOptions`. Required feature specification, target and dialect stay
keyword arguments. This signature meets the argument-count lint bar.

The shell verifies header-less DuckDB SQL against every source row before
returning an export in any supported dialect. A mismatch returns HTTP 500 with
the first source row id and a recovery step, logs the failure, and withholds SQL.
`GET /export` exports the current workspace's rule and, like every route
except `/health`, requires the launch session ([ADR 0010](0010-localhost-security.md)).
