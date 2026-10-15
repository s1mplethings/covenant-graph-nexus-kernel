from __future__ import annotations

import pytest

from cgkn.agent.composer import AgentDecision
from cgkn.agent.project_loop import AgentProjectLoop
from cgkn.orchestration.tree_edits import TreeEdit
from cgkn.providers import ModelRoleConfig
from cgkn.state import FileRunStore


pytestmark = [pytest.mark.negative, pytest.mark.boundary]


class Composer:
    config = ModelRoleConfig("agent", "agent")
    def __init__(self, decisions): self.decisions = list(decisions)
    def decide(self, _context): return self.decisions.pop(0)


class Runner:
    def run(self, **_kwargs): raise AssertionError("runner must not be called")


def decision(*, edits=(), run=False, finish=False, escalation=False):
    return AgentDecision("d", "summary", "reason", tuple(edits), run, finish, escalation, "review" if escalation else "", {}, "hash", 1)


def loop(tmp_path, decisions, **kwargs):
    return AgentProjectLoop(Composer(decisions), Runner(), FileRunStore(tmp_path), known_capabilities={"c@1"}, worker_model="worker", **kwargs)


def test_constructor_rejects_same_model_and_invalid_limit(tmp_path) -> None:
    with pytest.raises(ValueError, match="different"):
        AgentProjectLoop(Composer([]), Runner(), FileRunStore(tmp_path), known_capabilities=set(), worker_model="agent")
    with pytest.raises(ValueError, match="between"):
        loop(tmp_path, [], max_decisions=5)


def test_escalation_and_finish_before_run_are_fail_closed(tmp_path) -> None:
    blocked = loop(tmp_path / "a", [decision(escalation=True)]).run(project_id="p", run_id="r", goal="g")
    assert blocked.status == "BLOCKED" and blocked.escalation_reason == "review"
    finished = loop(tmp_path / "b", [decision(finish=True)]).run(project_id="p", run_id="r", goal="g")
    assert finished.status == "FAILED" and finished.as_dict()["run_summary"] is None


def test_multiple_retry_and_empty_run_are_rejected(tmp_path) -> None:
    retries = (
        TreeEdit("e1", "retry_node", "n", {}, {"actor": "agent"}),
        TreeEdit("e2", "retry_node", "n", {}, {"actor": "agent"}),
    )
    with pytest.raises(ValueError, match="at most one"):
        loop(tmp_path / "a", [decision(edits=retries)]).run(project_id="p", run_id="r", goal="g")
    with pytest.raises(ValueError, match="no executable"):
        loop(tmp_path / "b", [decision(run=True)]).run(project_id="p", run_id="r", goal="g")


def test_decision_limit_blocks_without_false_success(tmp_path) -> None:
    result = loop(tmp_path, [decision()], max_decisions=1).run(project_id="p", run_id="r", goal="g")
    assert result.status == "BLOCKED" and result.escalation_reason == "agent decision limit reached"
