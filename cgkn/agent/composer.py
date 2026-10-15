from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.orchestration.capability_tree import CapabilityTree, _thaw
from cgkn.orchestration.tree_edits import TreeEdit
from cgkn.providers import CompletionClient, ModelRoleConfig, ProviderCompletion, parse_json_object

from .composer_contract import parse_tree_edit


AGENT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "decision_id", "summary", "reason", "edits", "request_run", "finish", "needs_escalation", "escalation_reason"],
    "properties": {
        "schema_version": {"const": "1.0"}, "decision_id": {"type": "string"}, "summary": {"type": "string"}, "reason": {"type": "string"},
        "edits": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["edit_id", "operation", "node_id", "payload", "provenance"], "properties": {
            "edit_id": {"type": "string"}, "operation": {"enum": ["add_node", "remove_node", "replace_node", "move_node", "add_dependency", "remove_dependency", "replace_executor", "update_config", "retry_node"]}, "node_id": {"type": "string"},
            "payload": {"type": "object"}, "provenance": {"type": "object"}
        }}}, "request_run": {"type": "boolean"}, "finish": {"type": "boolean"},
        "needs_escalation": {"type": "boolean"}, "escalation_reason": {"type": "string"},
    },
}


@dataclass(frozen=True)
class AgentDecisionContext:
    project_id: str
    run_id: str
    goal: str
    decision_number: int
    tree: CapabilityTree
    known_capabilities: tuple[str, ...]
    capability_catalog: Mapping[str, Any]
    run_summary: Mapping[str, Any]
    failure_details: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "run_id": self.run_id, "goal": self.goal, "decision_number": self.decision_number, "tree": self.tree.as_dict(), "known_capabilities": list(self.known_capabilities), "capability_catalog": _thaw(self.capability_catalog), "run_summary": _thaw(self.run_summary), "failure_details": _thaw(self.failure_details)}


@dataclass(frozen=True)
class AgentDecision:
    decision_id: str
    summary: str
    reason: str
    edits: tuple[TreeEdit, ...]
    request_run: bool
    finish: bool
    needs_escalation: bool
    escalation_reason: str
    provider: Mapping[str, Any]
    context_hash: str
    context_chars: int

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "decision_id": self.decision_id, "summary": self.summary, "reason": self.reason, "edits": [{"edit_id": item.edit_id, "operation": item.operation, "node_id": item.node_id, "payload": _thaw(item.payload), "provenance": _thaw(item.provenance)} for item in self.edits], "request_run": self.request_run, "finish": self.finish, "needs_escalation": self.needs_escalation, "escalation_reason": self.escalation_reason, "provider": _thaw(self.provider), "context_hash": self.context_hash, "context_chars": self.context_chars}


def parse_agent_decision(value: Mapping[str, Any], completion: ProviderCompletion, raw_context: str) -> AgentDecision:
    required = set(AGENT_SCHEMA["required"])
    if set(value) != required or value.get("schema_version") != "1.0":
        raise ValueError("agent decision has invalid envelope")
    edits_raw = value.get("edits")
    if not isinstance(edits_raw, list):
        raise ValueError("agent edits must be a list")
    normalized_edits: list[dict[str, Any]] = []
    for raw in edits_raw:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        payload = dict(item.get("payload", {}))
        if item.get("operation") == "add_node" and payload.get("parent_id") in {None, "root"}:
            payload["parent_id"] = ""
        item["payload"] = payload
        normalized_edits.append(item)
    edits = tuple(parse_tree_edit(item) for item in normalized_edits)
    if len(edits) != len(edits_raw):
        raise ValueError("agent edit must be an object")
    if any(item.operation not in {"add_node", "remove_node", "replace_node", "move_node", "add_dependency", "remove_dependency", "replace_executor", "update_config", "retry_node"} for item in edits):
        raise ValueError("agent proposed an unauthorized operation")
    for item in edits:
        if item.operation == "add_node":
            if set(item.payload) != {"capability_ref", "parent_id", "depends_on", "config"} or not str(item.payload.get("capability_ref", "")):
                raise ValueError("agent add_node payload is not canonical")
        elif item.operation == "update_config" and set(item.payload) != {"config"}:
            raise ValueError("agent update_config payload is not canonical")
        elif item.operation == "retry_node" and item.payload:
            raise ValueError("agent retry_node payload must be empty")
    controls = sum(bool(value[name]) for name in ("request_run", "finish", "needs_escalation"))
    if controls != 1:
        raise ValueError("agent decision must choose exactly one control outcome")
    return AgentDecision(str(value["decision_id"]), str(value["summary"]), str(value["reason"]), edits, bool(value["request_run"]), bool(value["finish"]), bool(value["needs_escalation"]), str(value["escalation_reason"]), {"model": completion.model, "request_id": completion.request_id, "usage": dict(completion.usage), "attempts": completion.attempts}, hashlib.sha256(raw_context.encode()).hexdigest(), len(raw_context))


class AgentComposer:
    def __init__(self, client: CompletionClient, config: ModelRoleConfig):
        if config.role != "agent":
            raise ValueError("AgentComposer requires agent model config")
        self.client, self.config = client, config

    def decide(self, context: AgentDecisionContext) -> AgentDecision:
        raw_context = json.dumps(context.as_dict(), ensure_ascii=False, sort_keys=True)
        completion = self.client.complete(system="""You are the CGKN composition Agent. Decide only validated CapabilityTree edits and whether to run, finish, or escalate. Never write files, execute shell/network, change the project goal, package, deliver, or reveal hidden reasoning. Return concise JSON only.
Canonical edit syntax is exact: add_node payload is {\"capability_ref\": str, \"parent_id\": str, \"depends_on\": [str], \"config\": object}; update_config payload is {\"config\": object}; retry_node payload is {}. Executor selection belongs in config.executor_ref. Copy config keys and values exactly from capability_catalog; do not invent aliases or absolute paths. Use capability_ref, depends_on, and executor_ref exactly; never substitute capability, dependencies, tool, runner, model, command, instruction, target_file, or file_path. For this MVP, every added node must have a non-empty known capability_ref. A request_run decision must create or retain at least one executable node.""", user=raw_context, schema_name="cgkn_agent_decision", schema=AGENT_SCHEMA, config=self.config)
        return parse_agent_decision(parse_json_object(completion.text), completion, raw_context)
