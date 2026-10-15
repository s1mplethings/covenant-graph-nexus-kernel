from __future__ import annotations

import json

import pytest

from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.state import FileRunStore, NodeExecutionRecord, RunState, StateStoreError


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


def test_corrupt_state_and_path_traversal_fail_closed(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    path = store.run_dir("p", "r") / "run_state.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StateStoreError):
        store.load_run("p", "r")
    with pytest.raises(StateStoreError):
        store.run_dir("../escape", "r")
