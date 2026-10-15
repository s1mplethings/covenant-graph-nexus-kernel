from __future__ import annotations

import sys

from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors import CommandExecutor, ExecutorRegistry, FileExecutor
from cgkn.executors import ExecutorDescriptor
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore


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
