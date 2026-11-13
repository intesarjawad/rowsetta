from pathlib import Path
from time import perf_counter

from rowsetta.core.table import load_csv

DATASETS = Path(__file__).resolve().parents[1] / "src" / "rowsetta" / "datasets"


def main() -> None:
    """Measure bundled CSV loading, including reading bytes and inferring kinds."""
    for name in ("penguins", "bank", "adult", "bank_2k", "adult_2k"):
        start = perf_counter()
        table = load_csv((DATASETS / f"{name}.csv").read_bytes())
        elapsed = perf_counter() - start
        print(f"{name}.csv: {len(table.frame)} rows, {len(table.columns)} columns, {elapsed:.6f} s")


if __name__ == "__main__":
    main()
