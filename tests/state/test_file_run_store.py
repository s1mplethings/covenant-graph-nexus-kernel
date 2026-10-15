from __future__ import annotations

import json

import pytest

from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.state import EventRecord, FileRunStore, NodeExecutionRecord, ProjectState, RunState, StateStoreError


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def test_state_round_trip_atomic_and_resume_success(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    state = RunState("p", "r", status="SUCCEEDED", nodes={"n": NodeExecutionRecord("n", "SUCCEEDED", ["a1"], "node_results/n.json")})
    path = store.save_run(state)
    assert store.load_run("p", "r").nodes["n"].status == "SUCCEEDED"
    assert not list(path.parent.glob(".run_state.json.*"))


def test_attempt_history_never_overwrites(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    for attempt in ("a1", "a2"):
        store.save_result(BlockExecutionResult(project_id="p", run_id="r", attempt_id=attempt, node_id="n", executor_ref="e", status=BlockStatus.SUCCEEDED, outputs={"attempt": attempt}))
    assert (store.run_dir("p", "r") / "attempts/n/a1.json").is_file()
    assert (store.run_dir("p", "r") / "attempts/n/a2.json").is_file()
    assert store.load_result("p", "r", "n").outputs["attempt"] == "a2"
    duplicate = BlockExecutionResult(project_id="p", run_id="r", attempt_id="a2", node_id="n", executor_ref="e", status=BlockStatus.SUCCEEDED)
    with pytest.raises(StateStoreError, match="already exists"):
        store.save_result(duplicate)


def test_corrupt_state_and_path_traversal_fail_closed(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    path = store.run_dir("p", "r") / "run_state.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StateStoreError):
        store.load_run("p", "r")
    with pytest.raises(StateStoreError):
        store.run_dir("../escape", "r")
    with pytest.raises(StateStoreError):
        store.atomic_json(tmp_path.parent / "escape.json", {})
    escaped = BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="../escape", executor_ref="e", status=BlockStatus.SUCCEEDED)
    with pytest.raises(StateStoreError):
        store.save_result(escaped)


def test_event_log_round_trip_and_corruption_fail_closed(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    event = EventRecord("event.1", "p", "r", "RUN_CREATED", data={"source": "test"})
    store.append_event(event)
    assert store.load_events("p", "r") == (event,)
    (store.run_dir("p", "r") / "events.jsonl").write_text("{broken\n", encoding="utf-8")
    with pytest.raises(StateStoreError, match="cannot load event log"):
        store.load_events("p", "r")


@pytest.mark.negative
@pytest.mark.parametrize("segment", ["", ".", "..", "a/b", "a\\b"])
def test_all_invalid_state_path_segments_are_rejected(tmp_path, segment) -> None:
    store = FileRunStore(tmp_path)
    with pytest.raises(StateStoreError, match="invalid state identity"):
        store.run_dir(segment, "r")


@pytest.mark.negative
def test_definition_and_agent_decision_constraints(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    with pytest.raises(StateStoreError, match="unsupported definition"):
        store.save_definition("p", "r", "other.json", {})
    with pytest.raises(StateStoreError, match="positive"):
        store.save_agent_decision("p", "r", 0, {})
    path = store.save_agent_decision("p", "r", 1, {"decision": "continue"})
    assert path.is_file()
    with pytest.raises(StateStoreError, match="already exists"):
        store.save_agent_decision("p", "r", 1, {})


@pytest.mark.fault_injection
@pytest.mark.security
@pytest.mark.recovery
def test_symlink_and_atomic_replace_failure_fail_closed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FileRunStore(tmp_path)
    path = store.run_dir("p", "r") / "run_state.json"
    monkeypatch.setattr(type(path), "is_symlink", lambda _self: True)
    with pytest.raises(StateStoreError, match="symlink"):
        store.atomic_json(path, {})
    monkeypatch.undo()
    monkeypatch.setattr("cgkn.state.store.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("replace")))
    with pytest.raises(OSError, match="replace"):
        store.atomic_json(path, {})
    assert not list(path.parent.glob(".run_state.json.*"))


@pytest.mark.roundtrip
def test_project_definitions_summary_and_corrupt_result(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    project_path = store.save_project(ProjectState("p", "goal", "r"))
    assert project_path.is_file()
    for name in ("capability_tree.json", "execution_dag.json"):
        assert store.save_definition("p", "r", name, {"kind": name}).is_file()
    assert store.save_run_summary("p", "r", {"status": "SUCCEEDED"}).is_file()
    result_path = store.run_dir("p", "r") / "node_results" / "n.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StateStoreError, match="cannot load node result"):
        store.load_result("p", "r", "n")
    with pytest.raises(StateStoreError, match="cannot load run state"):
        store.load_run("p", "missing")


@pytest.mark.negative
def test_resolved_escape_guard_is_independently_enforced(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FileRunStore(tmp_path / "root")
    monkeypatch.setattr(FileRunStore, "_validate_segment", staticmethod(lambda _value: None))
    with pytest.raises(StateStoreError, match="escapes"):
        store.run_dir("..", "escape")
