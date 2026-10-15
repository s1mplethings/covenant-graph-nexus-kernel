from __future__ import annotations

import sys

import pytest

from cgkn.execution import BlockExecutionRequest, BlockStatus, TaskContext
from cgkn.executors import CommandExecutor, ExecutorRegistry, ExecutorResolutionError, FileExecutor


def req(executor_ref: str, config: dict, *, timeout: float = 5) -> BlockExecutionRequest:
    return BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="c@1", executor_ref=executor_ref, task_context=TaskContext("goal", config), timeout_seconds=timeout)


def test_registry_rejects_duplicates_disabled_and_unsupported(tmp_path) -> None:
    registry = ExecutorRegistry()
    executor = FileExecutor(tmp_path)
    registry.register(executor)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(executor)
    with pytest.raises(ExecutorResolutionError, match="not found"):
        registry.resolve("missing", "c@1")


def test_file_executor_is_real_and_confined(tmp_path) -> None:
    executor = FileExecutor(tmp_path)
    result = executor.execute(req("local.file@1", {"action": "write_file", "path": "hello.txt", "content": "hello"}))
    assert result.status is BlockStatus.SUCCEEDED
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello"
    escaped = executor.execute(req("local.file@1", {"action": "write_file", "path": "../escape.txt", "content": "bad"}))
    assert escaped.error.code.value == "POLICY_BLOCKED"


def test_command_executor_records_output_and_rejects_dangerous_commands(tmp_path) -> None:
    executor = CommandExecutor(tmp_path)
    result = executor.execute(req("local.command@1", {"command": [sys.executable, "-c", "print('ok')"], "cwd": "."}))
    assert result.status is BlockStatus.SUCCEEDED
    assert result.outputs["stdout"].strip() == "ok"
    rejected = executor.execute(req("local.command@1", {"command": ["git", "reset", "--hard"], "cwd": "."}))
    assert rejected.error.code.value == "POLICY_BLOCKED"
