import os

import pytest

from scripts.bench_teacher import drift_accuracy


@pytest.mark.model
@pytest.mark.skipif(os.environ.get("ROWSETTA_RUN_MODEL") != "1", reason="Set ROWSETTA_RUN_MODEL=1")
def test_penguins_six_labels_accuracy() -> None:
    accuracy = drift_accuracy()
    assert accuracy >= 0.80, f"penguins 6 labels accuracy={accuracy:.9f}"
