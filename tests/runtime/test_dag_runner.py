from __future__ import annotations

import sys

import pytest

from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors import CommandExecutor, ExecutorRegistry, FileExecutor
from cgkn.executors import ExecutorDescriptor
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.state import RunState, NodeExecutionRecord, StateStoreError


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def registry(project_root):
    value = ExecutorRegistry()
    value.register(FileExecutor(project_root))
    value.register(CommandExecutor(project_root))
    return value


def hello_tree() -> CapabilityTree:
    return CapabilityTree("hello", (
        CapabilityNode("project"),
        CapabilityNode("write", "project", "source.write@1", config={"executor_ref": "local.file@1", "action": "write_file", "path": "hello.py", "content": "print('runtime hello')\n"}),
        CapabilityNode("run", "project", "program.run@1", ("write",), {"executor_ref": "local.command@1", "command": [sys.executable, "hello.py"]}),
        CapabilityNode("verify", "project", "output.verify@1", ("run",), {"executor_ref": "local.command@1", "assert_dependency_stdout_contains": "runtime hello"}),
    ))


def test_real_vertical_slice_and_resume(tmp_path) -> None:
    project, runs = tmp_path / "project", tmp_path / "runs"
    project.mkdir()
    tree = hello_tree()
    runner = DAGRunner(registry(project), FileRunStore(runs))
    first = runner.run(project_id="p", run_id="r", tree=tree, dag=compile_tree(tree))
    assert first.status == "SUCCEEDED"
    assert first.actual_executions == ("write", "run", "verify")
    assert "runtime hello" in FileRunStore(runs).load_result("p", "r", "run").outputs["stdout"]
    second = runner.run(project_id="p", run_id="r", tree=tree, dag=compile_tree(tree), resume=True)
    assert second.actual_executions == ()
    assert second.reused_nodes == ("write", "run", "verify")


def test_failure_propagation_and_retry_history(tmp_path) -> None:
    project, runs = tmp_path / "project", tmp_path / "runs"
    project.mkdir()
    tree = CapabilityTree("broken", (
        CapabilityNode("write", capability_ref="source.write@1", config={"executor_ref": "local.file@1", "action": "write_file", "path": "broken.py", "content": "raise RuntimeError('broken')\n"}),
        CapabilityNode("run", capability_ref="program.run@1", depends_on=("write",), config={"executor_ref": "local.command@1", "command": [sys.executable, "broken.py"]}),
        CapabilityNode("verify", capability_ref="output.verify@1", depends_on=("run",), config={"executor_ref": "local.command@1", "assert_dependency_stdout_contains": "never"}),
    ))
    runner = DAGRunner(registry(project), FileRunStore(runs))
    first = runner.run(project_id="p", run_id="r", tree=tree, dag=compile_tree(tree))
    assert first.failed_nodes == ("run",)
    assert first.blocked_nodes == ("verify",)
    second = runner.run(project_id="p", run_id="r", tree=tree, dag=compile_tree(tree), retry_node="run")
    assert "write" in second.reused_nodes
    assert set(second.actual_executions) == {"run"}
    assert len(FileRunStore(runs).load_run("p", "r").nodes["run"].attempts) == 2


class RecordingExecutor:
    descriptor = ExecutorDescriptor("recording@1", "deterministic", ("*",))

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail: set[str] = {"test"}

    def execute(self, request):
        self.calls.append(request.node_id)
        if request.node_id in self.fail:
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "controlled failure"), retryable=True)
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.SUCCEEDED, outputs={"node": request.node_id})


def test_affected_subgraph_rerun_reuses_unaffected_successes(tmp_path) -> None:
    nodes = (
        CapabilityNode("inspect", capability_ref="inspect@1", config={"executor_ref": "recording@1"}),
        CapabilityNode("research", capability_ref="research@1", config={"executor_ref": "recording@1"}),
        CapabilityNode("implement", capability_ref="implement@1", depends_on=("inspect", "research"), config={"executor_ref": "recording@1"}),
        CapabilityNode("test", capability_ref="test@1", depends_on=("implement",), config={"executor_ref": "recording@1"}),
        CapabilityNode("report", capability_ref="report@1", depends_on=("test",), config={"executor_ref": "recording@1"}),
    )
    tree = CapabilityTree("local repair", nodes)
    executor = RecordingExecutor()
    executors = ExecutorRegistry()
    executors.register(executor)
    store = FileRunStore(tmp_path / "runs")
    runner = DAGRunner(executors, store)
    first = runner.run(project_id="p", run_id="r", tree=tree, dag=compile_tree(tree))
    assert first.failed_nodes == ("test",) and first.blocked_nodes == ("report",)
    executor.fail.clear()
    executor.calls.clear()
    repaired = runner.run(project_id="p", run_id="r", tree=tree, dag=compile_tree(tree), retry_node="test")
    assert repaired.status == "SUCCEEDED"
    assert repaired.actual_executions == ("test", "report")
    assert repaired.reused_nodes == ("inspect", "research", "implement")
    assert executor.calls == ["test", "report"]
    state = store.load_run("p", "r")
    assert len(state.nodes["test"].attempts) == 2
    assert len(state.nodes["inspect"].attempts) == 1


@pytest.mark.negative
def test_runner_rejects_tree_dag_and_persisted_state_mismatch(tmp_path) -> None:
    tree = CapabilityTree("goal", (CapabilityNode("n", capability_ref="c@1", config={"executor_ref": "recording@1"}),))
    empty = compile_tree(CapabilityTree("empty", ()))
    runner = DAGRunner(ExecutorRegistry(), FileRunStore(tmp_path / "runs"))
    with pytest.raises(ValueError, match="does not match"):
        runner.run(project_id="p", run_id="r", tree=tree, dag=empty)
    store = FileRunStore(tmp_path / "runs2")
    store.save_run(RunState("p", "r", nodes={"other": NodeExecutionRecord("other")}))
    with pytest.raises(ValueError, match="persisted run state"):
        DAGRunner(ExecutorRegistry(), store).run(project_id="p", run_id="r", tree=tree, dag=compile_tree(tree), resume=True)


@pytest.mark.recovery
def test_missing_resume_state_fails_but_new_run_recovers_from_initial_load_race(tmp_path, monkeypatch) -> None:
    tree = CapabilityTree("empty", ())
    store = FileRunStore(tmp_path / "runs")
    runner = DAGRunner(ExecutorRegistry(), store)
    with pytest.raises(StateStoreError):
        runner.run(project_id="p", run_id="missing", tree=tree, dag=compile_tree(tree), resume=True)
    original = store.load_run
    monkeypatch.setattr(store, "load_run", lambda *_args: (_ for _ in ()).throw(StateStoreError("race")))
    summary = runner.run(project_id="p", run_id="new", tree=tree, dag=compile_tree(tree))
    assert summary.status == "SUCCEEDED" and summary.node_count == 0
    monkeypatch.setattr(store, "load_run", original)


class RaisingExecutor:
    descriptor = ExecutorDescriptor("raising@1", "fault", ("*",))
    def execute(self, request):
        raise RuntimeError(f"boom {request.node_id}")


@pytest.mark.fault_injection
def test_executor_resolution_and_unhandled_exception_fail_closed(tmp_path) -> None:
    missing_tree = CapabilityTree("missing", (CapabilityNode("missing", capability_ref="c@1", config={"executor_ref": "absent@1"}),))
    runner = DAGRunner(ExecutorRegistry(), FileRunStore(tmp_path / "missing"))
    result = runner.run(project_id="p", run_id="r", tree=missing_tree, dag=compile_tree(missing_tree))
    assert result.failed_nodes == ("missing",)
    assert runner.store.load_result("p", "r", "missing").error.code is ExecutionErrorCode.EXECUTOR_NOT_FOUND
    registry = ExecutorRegistry(); registry.register(RaisingExecutor())
    raised_tree = CapabilityTree("raised", (CapabilityNode("raised", capability_ref="c@1", config={"executor_ref": "raising@1"}),))
    raised_runner = DAGRunner(registry, FileRunStore(tmp_path / "raised"))
    raised = raised_runner.run(project_id="p", run_id="r", tree=raised_tree, dag=compile_tree(raised_tree))
    failure = raised_runner.store.load_result("p", "r", "raised")
    assert raised.failed_nodes == ("raised",) and failure.retryable


@pytest.mark.determinism
def test_summary_and_event_order_are_deterministic(tmp_path) -> None:
    project = tmp_path / "project"; project.mkdir()
    store = FileRunStore(tmp_path / "runs")
    summary = DAGRunner(registry(project), store).run(project_id="p", run_id="r", tree=hello_tree(), dag=compile_tree(hello_tree()))
    assert summary.as_dict()["actual_executions"] == ["write", "run", "verify"]
    event_types = [event.event_type for event in store.load_events("p", "r")]
    assert event_types[0] == "RUN_CREATED" and event_types[-1] == "RUN_FINISHED"
