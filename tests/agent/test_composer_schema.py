from __future__ import annotations

import json

import pytest

from cgkn.agent.composer import AgentComposer, AgentDecisionContext, parse_agent_decision
from cgkn.agent.composer_contract import parse_tree_edit
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.providers import ModelRoleConfig, ProviderCompletion


pytestmark = [pytest.mark.negative, pytest.mark.boundary, pytest.mark.security]


def completion(value=None):
    return ProviderCompletion(json.dumps(value or {}), "agent-model", "request", {"tokens": 1}, 1)


def decision(*, edits=(), run=True, finish=False, escalate=False):
    return {"schema_version": "1.0", "decision_id": "d", "summary": "s", "reason": "r", "edits": list(edits), "request_run": run, "finish": finish, "needs_escalation": escalate, "escalation_reason": "review" if escalate else ""}


def edit(operation, payload=None):
    return {"edit_id": "e", "operation": operation, "node_id": "n", "payload": payload or {}, "provenance": {"actor": "agent"}}


@pytest.mark.happy_path
@pytest.mark.roundtrip
def test_valid_decision_normalizes_root_and_deep_values() -> None:
    raw = decision(edits=[edit("add_node", {"capability_ref": "c@1", "parent_id": "root", "depends_on": [], "config": {"nested": {"x": [1]}}})])
    parsed = parse_agent_decision(raw, completion(), "context")
    value = parsed.as_dict()
    assert value["edits"][0]["payload"]["parent_id"] == ""
    assert value["edits"][0]["payload"]["config"] == {"nested": {"x": [1]}}
    assert parsed.context_chars == 7 and len(parsed.context_hash) == 64


@pytest.mark.parametrize("value,match", [
    ({"schema_version": "1.0"}, "envelope"),
    ({**decision(), "edits": "bad"}, "must be a list"),
    (decision(edits=["bad"]), "must be an object"),
    (decision(edits=[edit("request_run")]), "unauthorized"),
    (decision(edits=[edit("add_node", {"capability_ref": ""})]), "not canonical"),
    (decision(edits=[edit("update_config", {})]), "not canonical"),
    (decision(edits=[edit("retry_node", {"x": 1})]), "invalid tree edit payload"),
    (decision(run=False), "exactly one"),
    (decision(run=True, finish=True), "exactly one"),
])
@pytest.mark.fault_injection
def test_invalid_decision_matrix(value, match) -> None:
    with pytest.raises(ValueError, match=match):
        parse_agent_decision(value, completion(), "context")


def test_tree_edit_rejects_extra_fields() -> None:
    value = edit("retry_node"); value["shell"] = "no"
    with pytest.raises(ValueError, match="unknown tree edit"):
        parse_tree_edit(value)


def test_retry_payload_defense_rejects_nonempty_parsed_edit(monkeypatch) -> None:
    class Parsed:
        operation = "retry_node"
        payload = {"forbidden": True}
    monkeypatch.setattr("cgkn.agent.composer.parse_tree_edit", lambda _value: Parsed())
    with pytest.raises(ValueError, match="must be empty"):
        parse_agent_decision(decision(edits=[edit("retry_node")]), completion(), "context")


class Client:
    def __init__(self, value): self.value = value
    def complete(self, **_kwargs): return completion(self.value)


@pytest.mark.happy_path
def test_composer_decide_serializes_context_without_hidden_reasoning() -> None:
    value = decision(run=False, finish=True)
    composer = AgentComposer(Client(value), ModelRoleConfig("agent", "agent-model"))
    context = AgentDecisionContext("p", "r", "goal", 1, CapabilityTree("goal", ()), (), {"nested": {"x": [1]}}, {}, {})
    result = composer.decide(context)
    assert result.finish and "reasoning" not in json.dumps(result.as_dict()).lower()
    with pytest.raises(ValueError, match="agent model"):
        AgentComposer(Client(value), ModelRoleConfig("worker", "worker-model"))
