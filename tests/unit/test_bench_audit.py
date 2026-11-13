import pytest

from rowsetta.teachers.fake import FakeTeacher
from scripts.bench_audit import FLIP_RATE, flip_labels, measure, parser


def test_flips_are_seeded_and_always_change_the_label() -> None:
    labels = {row: "ab"[row % 2] for row in range(200)}
    first, flipped = flip_labels(labels, ("a", "b"), seed=7)
    again, flipped_again = flip_labels(labels, ("a", "b"), seed=7)
    assert (first, flipped) == (again, flipped_again)
    assert len(flipped) == round(FLIP_RATE * len(labels))
    assert all(first[row] != labels[row] for row in flipped)
    assert all(first[row] == labels[row] for row in labels.keys() - flipped)


def test_audit_beats_random_on_penguins() -> None:
    result = measure("penguins", FakeTeacher())
    assert result.k == round(FLIP_RATE * 344)
    assert result.precision > FLIP_RATE
    assert result.p_value < 0.01


def test_unknown_teacher_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(["--teacher", "forest"])
    assert "invalid choice" in capsys.readouterr().err
