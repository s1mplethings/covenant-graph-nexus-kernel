from __future__ import annotations

import json

import pytest

from cgkn.execution import BlockExecutionRequest, BlockStatus, TaskContext
from cgkn.executors.llm import BoundedFileActions, LLMExecutor, ProposalError, validate_worker_proposal
from cgkn.providers import ModelRoleConfig, ProviderCompletion


pytestmark = [pytest.mark.boundary, pytest.mark.security]


class Client:
    def __init__(self, value=None, error: Exception | None = None):
        self.value, self.error = value, error

    def complete(self, **_kwargs):
        if self.error:
            raise self.error
        return ProviderCompletion(json.dumps(self.value), "worker", "request", {"total_tokens": 3}, 2)


def proposal(actions=(), *, escalation=False):
    return {"schema_version": "1.0", "node_id": "n", "summary": "bounded", "actions": list(actions), "expected_outputs": ["done"], "confidence": 0.8, "needs_escalation": escalation, "escalation_reason": "review" if escalation else ""}


def request():
    return BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="n", component_ref="c@1", executor_ref="llm.cheap@1", task_context=TaskContext("goal", {"nested": {"value": 1}}))


@pytest.mark.happy_path
def test_worker_actions_read_list_write_patch_and_usage(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    actions = [
        {"action": "read_file", "path": "a.txt"},
        {"action": "list_files", "path": "."},
        {"action": "write_file", "path": "b.txt", "content": "new"},
        {"action": "patch_file", "path": "a.txt", "find": "old", "replace": "fixed"},
    ]
    result = LLMExecutor(tmp_path, Client(proposal(actions)), ModelRoleConfig("worker", "worker")).execute(request())
    assert result.status is BlockStatus.SUCCEEDED
    assert result.outputs["modified_files"] == ("b.txt", "a.txt")
    assert result.usage["provider_attempts"] == 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "fixed"


@pytest.mark.negative
@pytest.mark.parametrize("mutation", [
    lambda value: value.update(schema_version="2"),
    lambda value: value.update(actions="bad"),
    lambda value: value.update(confidence=2),
    lambda value: value.update(actions=["bad"]),
    lambda value: value.update(actions=[{"action": "shell"}]),
    lambda value: value.update(needs_escalation=True, actions=[{"action": "read_file", "path": "a"}]),
])
def test_worker_proposal_rejects_malformed_values(mutation) -> None:
    value = proposal(); mutation(value)
    with pytest.raises(ProposalError):
        validate_worker_proposal(value, "n")


@pytest.mark.negative
@pytest.mark.parametrize("action", [
    {"action": "shell", "path": "."},
    {"action": "read_file", "path": ".", "extra": True},
])
def test_action_envelope_is_exact(tmp_path, action) -> None:
    with pytest.raises(ProposalError):
        BoundedFileActions(tmp_path).apply(action)


@pytest.mark.negative
def test_action_confinement_protected_paths_and_patch_ambiguity(tmp_path) -> None:
    actions = BoundedFileActions(tmp_path)
    with pytest.raises(PermissionError, match="escapes"):
        actions.apply({"action": "write_file", "path": "../x", "content": "x"})
    with pytest.raises(PermissionError, match="protected"):
        actions.apply({"action": "write_file", "path": ".git/config", "content": "x"})
    (tmp_path / "a.txt").write_text("same same", encoding="utf-8")
    with pytest.raises(ProposalError, match="exactly once"):
        actions.apply({"action": "patch_file", "path": "a.txt", "find": "same", "replace": "x"})


@pytest.mark.fault_injection
@pytest.mark.parametrize("error,status", [(TimeoutError("timeout"), BlockStatus.TIMED_OUT), (RuntimeError("provider"), BlockStatus.FAILED)])
def test_worker_provider_failures_are_results(tmp_path, error, status) -> None:
    result = LLMExecutor(tmp_path, Client(error=error), ModelRoleConfig("worker", "worker")).execute(request())
    assert result.status is status and result.error is not None
    assert result.retryable is True


@pytest.mark.negative
def test_worker_invalid_output_permission_and_escalation(tmp_path) -> None:
    with pytest.raises(ValueError, match="worker"):
        LLMExecutor(tmp_path, Client(proposal()), ModelRoleConfig("agent", "agent"))
    bad = LLMExecutor(tmp_path, Client({"bad": True}), ModelRoleConfig("worker", "worker")).execute(request())
    assert bad.status is BlockStatus.FAILED and bad.error.code.value == "INVALID_OUTPUT"
    escaped = LLMExecutor(tmp_path, Client(proposal([{"action": "write_file", "path": "../x", "content": "x"}])), ModelRoleConfig("worker", "worker")).execute(request())
    assert escaped.error.code.value == "POLICY_BLOCKED"
    blocked = LLMExecutor(tmp_path, Client(proposal(escalation=True)), ModelRoleConfig("worker", "worker")).execute(request())
    assert blocked.status is BlockStatus.BLOCKED and blocked.error.details["needs_escalation"] is True
