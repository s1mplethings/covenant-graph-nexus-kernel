from __future__ import annotations

import pytest

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, TaskContext


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def request() -> BlockExecutionRequest:
    return BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a1", node_id="n", component_ref="example@1", executor_ref="local.file@1", task_context=TaskContext("bounded goal"))


def test_request_contains_only_bounded_task_context() -> None:
    value = request().as_dict()
    assert value["schema_version"] == "1.0"
    assert set(value["task_context"]) == {"node_goal", "node_config", "dependency_results", "artifact_refs", "project_constraints", "acceptance"}
    assert "conversation" not in str(value).lower()
    assert BlockExecutionRequest.from_dict(value).as_dict() == value


def test_result_error_contract_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires an error"):
        BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.FAILED)
    result = BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, "bad"))
    assert BlockExecutionResult.from_dict(result.as_dict()).error.code is ExecutionErrorCode.INVALID_OUTPUT


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="c@1", executor_ref="e", task_context=TaskContext("goal"), timeout_seconds=0)


def test_nested_contract_values_are_immutable_and_result_status_is_consistent() -> None:
    source = {"nested": {"items": [1]}}
    value = BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="c@1", executor_ref="e", task_context=TaskContext("goal", node_config=source))
    source["nested"]["items"].append(2)
    assert value.task_context.node_config["nested"]["items"] == (1,)
    with pytest.raises(TypeError):
        value.task_context.node_config["nested"]["x"] = 1
    with pytest.raises(ValueError, match="must not contain"):
        BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.SUCCEEDED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "bad"))
    with pytest.raises(ValueError, match="TIMEOUT"):
        BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.TIMED_OUT, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, "bad"))


@pytest.mark.negative
@pytest.mark.security
@pytest.mark.parametrize("field", ["project_id", "run_id", "attempt_id", "node_id", "component_ref", "executor_ref"])
def test_request_rejects_each_empty_identity_field(field) -> None:
    values = {
        "project_id": "p", "run_id": "r", "attempt_id": "a", "node_id": "n",
        "component_ref": "c@1", "executor_ref": "e", "task_context": TaskContext("goal"),
    }
    values[field] = " "
    with pytest.raises(ValueError, match="required"):
        BlockExecutionRequest(**values)


@pytest.mark.negative
def test_empty_error_and_task_goal_are_rejected() -> None:
    with pytest.raises(ValueError, match="message"):
        ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, " ")
    with pytest.raises(ValueError, match="node_goal"):
        TaskContext(" ")


@pytest.mark.boundary
def test_result_identity_duration_and_succeeded_property() -> None:
    with pytest.raises(ValueError, match="identity"):
        BlockExecutionResult(project_id="", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.SUCCEEDED)
    with pytest.raises(ValueError, match="negative"):
        BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.SUCCEEDED, duration_ms=-1)
    succeeded = BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.SUCCEEDED)
    skipped = BlockExecutionResult(project_id="p", run_id="r", attempt_id="a", node_id="n", executor_ref="e", status=BlockStatus.SKIPPED)
    assert succeeded.succeeded is True
    assert skipped.succeeded is False


@pytest.mark.roundtrip
def test_nested_tuple_and_scalar_values_round_trip() -> None:
    value = request().as_dict()
    value["input_values"] = {"items": [1, {"ok": True}], "scalar": "value"}
    restored = BlockExecutionRequest.from_dict(value)
    assert restored.as_dict()["input_values"] == value["input_values"]
