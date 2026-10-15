from __future__ import annotations

import pytest

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, TaskContext


def request() -> BlockExecutionRequest:
    return BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a1", node_id="n", component_ref="example@1", executor_ref="local.file@1", task_context=TaskContext("bounded goal"))


def test_request_contains_only_bounded_task_context() -> None:
    value = request().as_dict()
    assert value["schema_version"] == "1.0"
    assert set(value["task_context"]) == {"node_goal", "node_config", "dependency_results", "artifact_refs", "project_constraints", "acceptance"}
    assert "conversation" not in str(value).lower()


def test_result_error_contract_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires an error"):
        BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.FAILED)
    result = BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, "bad"))
    assert BlockExecutionResult.from_dict(result.as_dict()).error.code is ExecutionErrorCode.INVALID_OUTPUT


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="c@1", executor_ref="e", task_context=TaskContext("goal"), timeout_seconds=0)
