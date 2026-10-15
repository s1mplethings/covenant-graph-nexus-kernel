from __future__ import annotations

import sys

import pytest

from cgkn.execution import BlockExecutionRequest, BlockStatus, TaskContext
from cgkn.executors import CommandExecutor, ExecutorFactoryRegistry, ExecutorRegistry, ExecutorResolutionError, FileExecutor, LocalActionExecutorAdapter, PythonTestExecutor
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.capabilities import CapabilityDescriptor


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def req(executor_ref: str, config: dict, *, timeout: float = 5) -> BlockExecutionRequest:
    return BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="c@1", executor_ref=executor_ref, task_context=TaskContext("goal", config), timeout_seconds=timeout)


@pytest.mark.determinism
def test_registry_rejects_duplicates_disabled_and_unsupported(tmp_path) -> None:
    registry = ExecutorRegistry()
    executor = FileExecutor(tmp_path)
    registry.register(executor)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(executor)
    with pytest.raises(ExecutorResolutionError, match="not found"):
        registry.resolve("missing", "c@1")
    with pytest.raises(ExecutorResolutionError, match="not found"):
        registry.unregister("missing")
    registry.unregister(executor.descriptor.executor_ref)
    assert registry.list() == ()


@pytest.mark.negative
def test_registry_rejects_disabled_and_unsupported_executor() -> None:
    class Stub:
        descriptor = ExecutorDescriptor("stub@1", "stub", ("only@1",), enabled=False)
        def execute(self, request): raise AssertionError(request)
    registry = ExecutorRegistry(); registry.register(Stub())
    with pytest.raises(ExecutorResolutionError, match="disabled"):
        registry.resolve("stub@1", "only@1")
    registry._executors["stub@1"].descriptor = ExecutorDescriptor("stub@1", "stub", ("only@1",))
    with pytest.raises(ExecutorResolutionError, match="does not support"):
        registry.resolve("stub@1", "other@1")


def test_file_executor_is_real_and_confined(tmp_path) -> None:
    executor = FileExecutor(tmp_path)
    result = executor.execute(req("local.file@1", {"action": "write_file", "path": "hello.txt", "content": "hello"}))
    assert result.status is BlockStatus.SUCCEEDED
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello"
    escaped = executor.execute(req("local.file@1", {"action": "write_file", "path": "../escape.txt", "content": "bad"}))
    assert escaped.error.code.value == "POLICY_BLOCKED"
    assert executor.execute(req("local.file@1", {"action": "read_file", "path": "hello.txt"})).outputs["content"] == "hello"
    assert executor.execute(req("local.file@1", {"action": "list_files", "path": "."})).outputs["files"] == ("hello.txt",)
    assert executor.execute(req("local.file@1", {"action": "bad"})).status is BlockStatus.FAILED


def test_command_executor_records_output_and_rejects_dangerous_commands(tmp_path) -> None:
    executor = CommandExecutor(tmp_path)
    result = executor.execute(req("local.command@1", {"command": [sys.executable, "-c", "print('ok')"], "cwd": "."}))
    assert result.status is BlockStatus.SUCCEEDED
    assert result.outputs["stdout"].strip() == "ok"
    rejected = executor.execute(req("local.command@1", {"command": ["git", "reset", "--hard"], "cwd": "."}))
    assert rejected.error.code.value == "POLICY_BLOCKED"


@pytest.mark.negative
@pytest.mark.fault_injection
def test_command_failure_timeout_contract_and_dependency_check(tmp_path, monkeypatch) -> None:
    executor = CommandExecutor(tmp_path)
    failed = executor.execute(req("local.command@1", {"command": [sys.executable, "-c", "raise SystemExit(4)"]}))
    assert failed.status is BlockStatus.FAILED and failed.retryable
    invalid = executor.execute(req("local.command@1", {"command": "shell text"}))
    assert invalid.error.code.value == "CONTRACT_ERROR"
    context = TaskContext("goal", {"assert_dependency_stdout_contains": "yes"}, dependency_results={"a": {"stdout": "no"}})
    dependency_request = BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="c@1", executor_ref="local.command@1", task_context=context)
    assert executor.execute(dependency_request).status is BlockStatus.FAILED
    matching_context = TaskContext("goal", {"assert_dependency_stdout_contains": "yes"}, dependency_results={"a": {"stdout": "yes"}})
    matching_request = BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a2", node_id="n", component_ref="c@1", executor_ref="local.command@1", task_context=matching_context)
    assert executor.execute(matching_request).status is BlockStatus.SUCCEEDED
    monkeypatch.setattr("cgkn.executors.local.subprocess.run", lambda *_a, **_k: (_ for _ in ()).throw(__import__("subprocess").TimeoutExpired("x", 1)))
    assert executor.execute(req("local.command@1", {"command": ["x"]})).status is BlockStatus.TIMED_OUT


@pytest.mark.local_functional
def test_python_test_and_local_action_adapter(tmp_path) -> None:
    (tmp_path / "test_ok.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    test_result = PythonTestExecutor(tmp_path).execute(req("local.python-test@1", {"pytest_args": ["-q", "test_ok.py"]}, timeout=20))
    assert test_result.status is BlockStatus.SUCCEEDED
    adapter = LocalActionExecutorAdapter(tmp_path)
    assert adapter.execute(req("local.action@1", {"action": "read_file", "path": "test_ok.py"})).status is BlockStatus.SUCCEEDED
    command = req("local.action@1", {"action": "run_command", "command": [sys.executable, "-c", "print('ok')"]})
    assert adapter.execute(command).status is BlockStatus.SUCCEEDED
    assert adapter.execute(req("local.action@1", {"action": "unknown"})).error.code.value == "CONTRACT_ERROR"


@pytest.mark.negative
def test_executor_factory_identity_resolution_and_mismatch(tmp_path) -> None:
    descriptor = CapabilityDescriptor("c", "1", "c@1", "local.file@1", ("python",), (), (), (), 1, "zero", "LOW", "local", {"implementation_identity": "file"}, ("test",))
    factories = ExecutorFactoryRegistry()
    with pytest.raises(ValueError, match="unique"):
        factories.register(" ", lambda _descriptor: FileExecutor(tmp_path))
    factories.register("file", lambda _descriptor: FileExecutor(tmp_path))
    with pytest.raises(ValueError, match="unique"):
        factories.register("file", lambda _descriptor: FileExecutor(tmp_path))
    assert factories.create(descriptor).descriptor.executor_ref == "local.file@1"
    missing = CapabilityDescriptor(**{**descriptor.__dict__, "capability_id": "missing", "provenance": {}})
    with pytest.raises(LookupError, match="missing"):
        factories.create(missing)
    wrong = ExecutorFactoryRegistry(); wrong.register("file", lambda _descriptor: CommandExecutor(tmp_path))
    with pytest.raises(ValueError, match="mismatched"):
        wrong.create(descriptor)
