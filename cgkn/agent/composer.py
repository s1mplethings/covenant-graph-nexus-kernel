from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from cgkn.orchestration.capability_tree import CapabilityTree, _thaw
from cgkn.orchestration.tree_edits import TreeEdit, EDIT_PAYLOAD_KEYS
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


# Advertise the same operation-specific payload boundary enforced by TreeEdit.
AGENT_SCHEMA['properties']['edits']['items']['allOf']=[
    {'if':{'properties':{'operation':{'const':operation}}},
     'then':{'properties':{'payload':{'type':'object','properties':{key:{} for key in sorted(keys)},
                                    'additionalProperties':False}}}}
    for operation,keys in sorted(EDIT_PAYLOAD_KEYS.items()) if operation in AGENT_SCHEMA['properties']['edits']['items']['properties']['operation']['enum']
]


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
    execution_results: Mapping[str, Any] = field(default_factory=dict)
    goal_acceptance: Mapping[str, Any] = field(default_factory=dict)
    task_feedback: Mapping[str, Any] = field(default_factory=dict)
    retrieved_knowledge: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "run_id": self.run_id, "goal": self.goal, "decision_number": self.decision_number, "tree": self.tree.as_dict(), "known_capabilities": list(self.known_capabilities), "capability_catalog": _thaw(self.capability_catalog), "run_summary": _thaw(self.run_summary), "failure_details": _thaw(self.failure_details), "execution_results": _thaw(self.execution_results), "goal_acceptance": _thaw(self.goal_acceptance), "task_feedback": _thaw(self.task_feedback), "retrieved_knowledge": _thaw(self.retrieved_knowledge)}


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
    goal_plan: Mapping[str, Any] | None = None
    decision_audit: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"decision_audit": _thaw(self.decision_audit), "schema_version": "1.0", "decision_id": self.decision_id, "summary": self.summary, "reason": self.reason, "edits": [{"edit_id": item.edit_id, "operation": item.operation, "node_id": item.node_id, "payload": _thaw(item.payload), "provenance": _thaw(item.provenance)} for item in self.edits], "request_run": self.request_run, "finish": self.finish, "needs_escalation": self.needs_escalation, "escalation_reason": self.escalation_reason, "provider": _thaw(self.provider), "context_hash": self.context_hash, "context_chars": self.context_chars, "goal_plan": _thaw(self.goal_plan) if self.goal_plan else None}


def parse_agent_decision(value: Mapping[str, Any], completion: ProviderCompletion, raw_context: str) -> AgentDecision:
    required = set(AGENT_SCHEMA["required"])
    if set(value) - {"goal_plan", "decision_audit"} != required or value.get("schema_version") != "1.0":
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
            if set(item.payload) != {"capability_ref", "parent_id", "depends_on", "config"}:
                raise ValueError("agent add_node payload is not canonical")
        elif item.operation == "update_config" and set(item.payload) != {"config"}:
            raise ValueError("agent update_config payload is not canonical")
        elif item.operation == "retry_node" and item.payload:
            raise ValueError("agent retry_node payload must be empty")
    controls = sum(bool(value[name]) for name in ("request_run", "finish", "needs_escalation"))
    if controls != 1 and not (controls == 0 and value.get("goal_plan")):
        raise ValueError("agent decision must choose exactly one control outcome")
    audit=value.get('decision_audit',{})
    if audit and (set(audit)!={'alternatives_considered','expected_outcome'} or not isinstance(audit['alternatives_considered'],list) or any(not isinstance(x,str) for x in audit['alternatives_considered']) or not isinstance(audit['expected_outcome'],str)):
        raise ValueError('invalid public decision audit')
    return AgentDecision(str(value["decision_id"]), str(value["summary"]), str(value["reason"]), edits, bool(value["request_run"]), bool(value["finish"]), bool(value["needs_escalation"]), str(value["escalation_reason"]), {"model": completion.model, "routing": dict(completion.routing), "request_id": completion.request_id, "usage": dict(completion.usage), "attempts": completion.attempts}, hashlib.sha256(raw_context.encode()).hexdigest(), len(raw_context), value.get("goal_plan"),audit)


class AgentDecisionValidationError(ValueError):
    """Rejected model text, preserved verbatim for the next bounded decision."""

    def __init__(self, error: Exception, completion: ProviderCompletion):
        super().__init__(str(error))
        self.feedback = {"error_type": type(error).__name__, "error": str(error),
                         "raw_response": completion.text, "model": completion.model,
                         "request_id": completion.request_id}


class AgentComposer:
    def __init__(self, client: CompletionClient, config: ModelRoleConfig, *, require_decision_audit=False, allow_goal_plan=True, semantic_tables=None, protocol_trace=None, context_resolver=None, context_policy=None):
        if config.role != "agent":
            raise ValueError("AgentComposer requires agent model config")
        self.client, self.config = client, config
        self.semantic_tables=semantic_tables
        self.protocol_trace=protocol_trace
        self.context_resolver,self.context_policy=context_resolver,context_policy
        if semantic_tables is not None and not callable(protocol_trace):raise ValueError("semantic protocol requires an audit sink")
        self.require_decision_audit,self.allow_goal_plan=require_decision_audit,allow_goal_plan

    def decide(self, context: AgentDecisionContext) -> AgentDecision:
        if self.semantic_tables is not None:
            from cgkn.protocol.adapters import semantic_decide
            return semantic_decide(self,context)
        from cgkn.orchestration.leaf_contract import CONTRACT_SCHEMA
        raw_context = json.dumps({**context.as_dict(),'execution_leaf_contract_schema':CONTRACT_SCHEMA}, ensure_ascii=False, sort_keys=True)
        schema=json.loads(json.dumps(AGENT_SCHEMA))
        if context.goal_acceptance and self.allow_goal_plan:
            schema["properties"]["goal_plan"]={"type":"object"}
        if self.require_decision_audit:
            schema['required'].append('decision_audit')
            schema['properties']['decision_audit']={'type':'object','additionalProperties':False,'required':['alternatives_considered','expected_outcome'],'properties':{'alternatives_considered':{'type':'array','items':{'type':'string'}},'expected_outcome':{'type':'string'}}}
        from cgkn.providers.gateway_client import GatewayCompletionError
        try:
            completion = self.client.complete(system="""You are the CGKN composition Agent. Decide only validated CapabilityTree edits and whether to run, finish, or escalate. Never write files, execute shell/network, change the project goal, package, deliver, or reveal hidden reasoning. Return concise JSON only.
    Exactly one of request_run, finish, needs_escalation must be true. Repair edits require request_run=true, finish=false, needs_escalation=false. Rejected decisions have not applied their edits; use validation feedback for a new decision.
    Canonical edit syntax is exact: add_node payload is {\"capability_ref\": str, \"parent_id\": str, \"depends_on\": [str], \"config\": object}; update_config payload is {\"config\": object}; retry_node payload is {}. Executor selection belongs in config.executor_ref. Copy config keys and values exactly from capability_catalog; do not invent aliases or absolute paths. Use capability_ref, depends_on, and executor_ref exactly; never substitute capability, dependencies, tool, runner, model, command, instruction, target_file, or file_path. Composite nodes have empty capability_ref and cannot execute. Every executable leaf requires config.leaf_contract with schema_version=1.0, leaf_goal, task_kind, target_scope (bounded relative artifact paths), expected_delta for writes, acceptance (registered checker condition names), checker_ref, output_identity, effect_domains (one primary), executor_ref and dependencies matching the node. Research requires source_refs and completion_criterion; tests require subject, expected_observation and pass_fail_rule. Choose independently verifiable deliverables, not whole products. NEEDS_DECOMPOSITION requires Agent revision; framework never splits business work. Execution success is not deliverable or goal acceptance. A request_run decision must create or retain at least one executable node.""", user=raw_context, schema_name="cgkn_agent_decision", schema=schema, config=self.config)
        except GatewayCompletionError as exc:
            document = getattr(exc, 'completed_response', None)
            if exc.category != 'schema_validation_failed' or exc.outcome_unknown or not isinstance(document, dict):
                raise
            text = document.get('output_text')
            if not isinstance(text, str):
                raise
            completion = ProviderCompletion(text, str(document.get('model') or 'UNKNOWN'),
                str(document.get('id') or ''), dict(document.get('usage') or {}),
                routing=dict(document.get('cgkn_model_identity') or {}))
            try:
                from jsonschema import Draft202012Validator
                value = parse_json_object(text)
                errors = [{'path': list(e.path), 'message': e.message}
                          for e in Draft202012Validator(schema).iter_errors(value)]
                reason = json.dumps(errors, ensure_ascii=False) if errors else str(exc)
            except ValueError as parse_error:
                reason = str(parse_error)
            rejection = AgentDecisionValidationError(ValueError(reason), completion)
            rejection.feedback.update(category=exc.category, failure_domain='MODEL_OUTPUT',
                outcome_unknown=False, usage=dict(completion.usage), routing=dict(completion.routing))
            raise rejection from exc

        try:
            value=parse_json_object(completion.text)
            if not self.allow_goal_plan and value.get('goal_plan'):raise ValueError('goal_plan is frozen; omit goal_plan, retain current acceptance contract')
            if self.require_decision_audit and not value.get('decision_audit'):raise ValueError('public decision_audit required: brief alternatives_considered and expected_outcome, no hidden reasoning')
            return parse_agent_decision(value, completion, raw_context)
        except (ValueError, TypeError, KeyError) as exc:
            # Transport errors remain outside this handler. No response repair.
            raise AgentDecisionValidationError(exc, completion) from exc
