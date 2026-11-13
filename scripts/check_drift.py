import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bench_common import BENCH_JSON, DOCUMENT
from scripts.bench_teacher import drift_accuracy

MAX_DRIFT = 0.02


def drift_exceeded(baseline: float, fresh: float) -> bool:
    """Accept an absolute change of at most two percentage points."""
    return abs(baseline - fresh) > MAX_DRIFT + 1e-12


def main() -> None:
    """Compare fresh teacher output with the fixed, recorded drift protocol."""
    document = DOCUMENT.validate_json(BENCH_JSON.read_text())
    teacher = document["teacher"]
    if not isinstance(teacher, dict) or not isinstance(teacher.get("penguins_6_labels"), dict):
        message = "Missing teacher.penguins_6_labels baseline"
        raise TypeError(message)
    measurement = teacher["penguins_6_labels"]
    if not isinstance(measurement, dict) or not isinstance(
        measurement.get("accuracy"), (int, float)
    ):
        message = "Missing teacher.penguins_6_labels.accuracy baseline"
        raise TypeError(message)
    baseline = measurement["accuracy"]
    if not isinstance(baseline, (int, float)):
        message = "Accuracy must be numeric"
        raise TypeError(message)
    fresh = drift_accuracy()
    print(f"baseline={baseline:.9f} fresh={fresh:.9f} absolute_drift={abs(baseline - fresh):.9f}")
    raise SystemExit(int(drift_exceeded(baseline, fresh)))


if __name__ == "__main__":
    main()
