import pytest

from rowsetta.core.errors import BadCsvError, NeedLabelsError, WorkspaceError
from rowsetta.core.session import LabelStore
from rowsetta.core.teacher import predict_table
from rowsetta.core.workspace import DEFAULT_THRESHOLD, Workspace
from rowsetta.teachers.fake import FakeTeacher


@pytest.fixture
def workspace() -> Workspace:
    workspace = Workspace()
    data = b"x,answer\n" + b"".join(
        f"{row},{'a' if row < 20 else 'b'}\n".encode() for row in range(40)
    )
    workspace.load(data, "source.csv", max_rows=40)
    workspace.set_target("answer", ("a", "b"))
    for row, label in ((0, "a"), (1, "a"), (38, "b"), (39, "b")):
        workspace.set_label(row, label, "human")
    return workspace


def refit(workspace: Workspace) -> None:
    result = predict_table(FakeTeacher(), workspace.require_table(), workspace.require_store())
    assert workspace.publish(result, workspace.generation)


def test_target_values_are_not_training_labels_and_invalid_target_is_atomic(
    workspace: Workspace,
) -> None:
    assert workspace.require_store().human == {0: "a", 1: "a", 38: "b", 39: "b"}
    before = workspace.require_store().to_json()
    with pytest.raises(WorkspaceError, match="does not exist"):
        workspace.set_target_from_column("missing")
    with pytest.raises(WorkspaceError, match="40 distinct values"):
        workspace.set_target_from_column("x")
    assert workspace.require_store().to_json() == before


def test_a_new_target_name_starts_an_empty_column(workspace: Workspace) -> None:
    workspace.set_target("urgent", ("yes", "no"))
    store = workspace.require_store()
    assert (store.target, store.classes, store.human) == ("urgent", ("yes", "no"), {})
    assert workspace.missing_labels() == {"yes": 2, "no": 2}


def test_a_column_target_prefills_labels_and_leaves_missing_values_unlabelled() -> None:
    workspace = Workspace()
    workspace.load(b"x,answer\n1,b\n2,\n3,a\n4,b\n", "source.csv", max_rows=40)
    workspace.set_target_from_column("answer")
    store = workspace.require_store()
    assert store.classes == ("a", "b")
    assert store.human == {0: "b", 2: "a", 3: "b"}
    assert store.undo_history == []


def test_new_sessions_start_at_the_default_abstention_threshold(workspace: Workspace) -> None:
    assert workspace.require_store().threshold == DEFAULT_THRESHOLD == 0.60
    workspace.set_target_from_column("answer")
    assert workspace.require_store().threshold == DEFAULT_THRESHOLD


def test_only_app_sessions_abstain_below_060_and_bare_label_stores_never_abstain(
    workspace: Workspace,
) -> None:
    assert workspace.require_store().threshold == 0.60
    assert LabelStore.model_fields["threshold"].default == 0.0


def test_last_feature_cannot_be_excluded(workspace: Workspace) -> None:
    with pytest.raises(WorkspaceError, match="No usable features"):
        workspace.exclude("x", excluded=True)
    assert workspace.require_store().excluded_columns == frozenset()


def test_stale_generation_cannot_publish_after_labels_are_cleared(workspace: Workspace) -> None:
    result = predict_table(FakeTeacher(), workspace.require_table(), workspace.require_store())
    generation = workspace.generation
    workspace.set_label(0, None, "human")
    assert workspace.missing_labels() == {"a": 1}
    assert not workspace.publish(result, generation)
    assert workspace.proposals is None
    with pytest.raises(NeedLabelsError) as failure:
        workspace.distill(4)
    assert failure.value.missing == {"a": 1}


def test_table_replacement_invalidates_session_and_in_flight_results(workspace: Workspace) -> None:
    result = predict_table(FakeTeacher(), workspace.require_table(), workspace.require_store())
    generation = workspace.generation
    workspace.load(b"number,outcome\n1,a\n2,b\n", "new.csv", max_rows=40)
    assert not workspace.publish(result, generation)
    assert workspace.store is None
    assert workspace.source is not None
    assert workspace.source.file_name == "new.csv"


def test_serving_eval_after_distillation_invalidates_the_student(workspace: Workspace) -> None:
    refit(workspace)
    workspace.distill(4)
    row = workspace.next_eval()
    assert row is not None
    assert workspace.student is None
    assert row != workspace.next_human()
    student = workspace.distill(4)
    assert row not in student.teacher_labels
    assert row in student.eval_rows


def test_raw_evaluation_is_independent_of_abstention(workspace: Workspace) -> None:
    for _ in range(20):
        row = workspace.next_eval()
        assert row is not None
        workspace.set_label(row, "a" if row < 20 else "b", "eval")
    refit(workspace)
    original = workspace.evaluation()
    assert original is not None
    workspace.set_threshold(1)
    refit(workspace)
    assert workspace.evaluation() == original
    proposals = workspace.require_proposals()
    assert proposals.abstained


@pytest.mark.parametrize("data", [b"", b"x,answer\n", b"\n\n"])
def test_empty_upload_keeps_the_previous_workspace(workspace: Workspace, data: bytes) -> None:
    table, store, source, generation = (
        workspace.table,
        workspace.store,
        workspace.source,
        workspace.generation,
    )
    with pytest.raises(BadCsvError, match="at least one data row"):
        workspace.load(data, "empty.csv", max_rows=40)
    assert workspace.table is table
    assert workspace.store is store
    assert workspace.source is source
    assert workspace.generation == generation
