import os
import sys

# These modules import native shells or their fixtures at collection time.
# Deselection with `-m not native` happens too late to prevent those imports.
# The CI floor job runs on CPython with only the packages Pyodide ships, so it opts in too.
collect_ignore = (
    [
        "test_bench_audit.py",
        "test_bench_pipeline.py",
        "test_bench_schema.py",
        "test_browser_build.py",
        "test_cli.py",
        "test_datasets.py",
        "test_dbt.py",
        "test_doctor.py",
        "test_exports.py",
        "test_sql.py",
        "test_sql_boundary.py",
        "test_tabicl_adapter.py",
        "test_teacher_bench.py",
    ]
    if sys.platform == "emscripten" or os.environ.get("ROWSETTA_PYODIDE_FLOOR") == "1"
    else []
)
