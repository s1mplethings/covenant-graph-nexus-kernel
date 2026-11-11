"""Project Agent boundary for VeriArbor.

A Project Agent (OpenCode, Codex, SuperAgent, or the embedded planner) has
proposal authority only. VeriArbor admission decides whether a proposal may
enter the authoritative CapabilityTree.

This module is intentionally thin: it reuses CapabilityTree, TreeEdit,
apply_tree_edits, compile_tree and the existing leaf-contract validation.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.leaf_contract import validate_leaf
from cgkn.orchestration.tree_edits import TreeEdit, apply_tree_edits

PROPOSAL_KIND = "ProjectProposal"
PROPOSAL_SCHEMA_VERSION = "1.0"
WRITING_KINDS = frozenset({"IMPLEMENTATION", "REPAIR", "INTEGRATION", "DELIVERY"})
REMOTE_EFFECTS = frozenset({
    "external_network", "external_post", "external_account", "credential_use",
    "remote_external_write", "publish",
})


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProjectProposal:
    proposal_id: str
    project_id: str
    base_tree_version: int
    goal_reference: str
    observed_evidence_refs: tuple[str, ...]
    proposed_operations: tuple[Mapping[str, Any], ...]
    requested_capability: str = ""
    repair_strategy: str = ""
    resource_preference: str = ""
    expected_progress: str = ""
    reason_summary: str = ""
    target_capability_id: str = ""
    target_gap_id: str = ""
    strategy_capabilities: tuple[str, ...] = ()
    exploration_reason: str = ""
    exploration_budget: float | None = None
    exploration_measure: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_capabilities, (tuple, list)) or any(
                not isinstance(item, str) or not item.strip() for item in self.strategy_capabilities):
            raise ValueError('strategy_capabilities must be capability IDs')
        object.__setattr__(self, 'strategy_capabilities', tuple(self.strategy_capabilities))
        if not self.proposal_id or not self.project_id:
            raise ValueError("proposal_id and project_id are required")
        if type(self.base_tree_version) is not int or self.base_tree_version < 0:
            raise ValueError("base_tree_version must be a non-negative integer")
        if not self.goal_reference:
            raise ValueError("goal_reference is required")
        if not isinstance(self.proposed_operations, tuple) or not self.proposed_operations:
            raise ValueError("at least one proposed operation is required")
        if not self.reason_summary.strip():
            raise ValueError("reason_summary is required")
        for operation in self.proposed_operations:
            if not isinstance(operation, Mapping):
                raise ValueError("each proposed operation must be an object")
            if not isinstance(operation.get("operation"), str) or not operation["operation"]:
                raise ValueError("each proposed operation needs an operation name")
            if not isinstance(operation.get("node_id"), str) or not operation["node_id"]:
                raise ValueError("each proposed operation needs a node_id")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": PROPOSAL_KIND, "schema_version": PROPOSAL_SCHEMA_VERSION,
            "proposal_id": self.proposal_id, "project_id": self.project_id,
            "base_tree_version": self.base_tree_version,
            "goal_reference": self.goal_reference,
            "observed_evidence_refs": list(self.observed_evidence_refs),
            "proposed_operations": [dict(item) for item in self.proposed_operations],
            "requested_capability": self.requested_capability,
            "repair_strategy": self.repair_strategy,
            "resource_preference": self.resource_preference,
            "expected_progress": self.expected_progress,
            "reason_summary": self.reason_summary,
            "target_capability_id": self.target_capability_id,
            "target_gap_id": self.target_gap_id,
            "strategy_capabilities": list(self.strategy_capabilities),
            "exploration_reason": self.exploration_reason,
            "exploration_budget": self.exploration_budget,
            "exploration_measure": self.exploration_measure,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectProposal":
        if value.get("kind") != PROPOSAL_KIND or value.get("schema_version") != PROPOSAL_SCHEMA_VERSION:
            raise ValueError("not a ProjectProposal v1.0 document")
        required = {
            "proposal_id", "project_id", "base_tree_version", "goal_reference",
            "observed_evidence_refs", "proposed_operations", "reason_summary",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError("proposal missing fields: " + ",".join(missing))
        refs = value.get("observed_evidence_refs")
        operations = value.get("proposed_operations")
        if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
            raise ValueError("observed_evidence_refs must be a string list")
        if not isinstance(operations, list):
            raise ValueError("proposed_operations must be a list")
        return cls(
            str(value["proposal_id"]), str(value["project_id"]),
            value["base_tree_version"], str(value["goal_reference"]), tuple(refs),
            tuple(dict(item) for item in operations),
            str(value.get("requested_capability", "")),
            str(value.get("repair_strategy", "")),
            str(value.get("resource_preference", "")),
            str(value.get("expected_progress", "")),
            str(value["reason_summary"]),
            str(value.get("target_capability_id", "")),
            str(value.get("target_gap_id", "")),
            tuple(value.get("strategy_capabilities", ())),
            str(value.get("exploration_reason", "")),
            value.get("exploration_budget"),
            str(value.get("exploration_measure", "")),
        )


@dataclass(frozen=True)
class RoadmapItem:
    item_id: str
    objective: str
    status: str = "PENDING"


@dataclass(frozen=True)
class ProjectRoadmap:
    """Longer-lived intent. Never an authoritative capability tree."""

    roadmap_id: str
    items: tuple[RoadmapItem, ...]

    def next_pending(self) -> RoadmapItem | None:
        return next((item for item in self.items if item.status == "PENDING"), None)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "ProjectRoadmap", "schema_version": "1.0",
                "roadmap_id": self.roadmap_id,
                "items": [{"item_id": i.item_id, "objective": i.objective,
                           "status": i.status} for i in self.items]}


@dataclass(frozen=True)
class AdmissionPolicy:
    incremental_mode: bool = True
    max_new_nodes: int = 1
    allowed_effect_domains: frozenset[str] = frozenset({"filesystem", "measurement", "local_process", "demo"})
    budget_state: str = "OK"       # OK | BLOCKED
    allow_remote_effects: bool = False
    require_leaf_contract: bool = True
    max_tree_edits: int = 8
    capability_contracts: Mapping[str, Any] = field(default_factory=dict)
    goal_gaps: Mapping[str, Any] = field(default_factory=dict)
    project_id: str = ""
    require_capability_contract: bool = False
    evidence_inputs: Mapping[str, Any] = field(default_factory=dict)
    execution_budget: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        domains = self.allowed_effect_domains
        if not isinstance(domains, (list, tuple, set, frozenset)) or any(
                not isinstance(domain, str) or not domain.strip() for domain in domains):
            raise ValueError("allowed_effect_domains must contain effect domain names")
        object.__setattr__(self, "allowed_effect_domains", frozenset(domains))

    def as_dict(self) -> dict[str, Any]:
        return {"incremental_mode": self.incremental_mode, "max_new_nodes": self.max_new_nodes,
                "allowed_effect_domains": sorted(self.allowed_effect_domains),
                "budget_state": self.budget_state, "allow_remote_effects": self.allow_remote_effects,
                "require_leaf_contract": self.require_leaf_contract,
                "max_tree_edits": self.max_tree_edits,
                "capability_contracts": dict(self.capability_contracts),
                "goal_gaps": dict(self.goal_gaps), "project_id": self.project_id,
                "require_capability_contract": self.require_capability_contract,
                "evidence_inputs": dict(self.evidence_inputs),
                "execution_budget": dict(self.execution_budget)}


@dataclass(frozen=True)
class AdmissionResult:
    valid: bool
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    edits: tuple[TreeEdit, ...] = ()
    preview: CapabilityTree | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "code": self.code, "message": self.message,
                "details": dict(self.details),
                "edits": [{"edit_id": e.edit_id, "operation": e.operation,
                           "node_id": e.node_id, "payload": dict(e.payload),
                           "provenance": dict(e.provenance)} for e in self.edits],
                "preview_tree_sha256": _digest(self.preview.as_dict()) if self.preview else None}


class ProjectAgent(Protocol):
    def propose(self, context: Mapping[str, Any]) -> ProjectProposal: ...


class ExternalFileProjectAgent:
    """Minimal file-based bridge used by OpenCode/Codex/SuperAgent.

    The external agent writes ``project_agent_proposal.json``; this adapter only
    loads and validates it. No network service and no second RPC stack.
    """

    def __init__(self, proposal_path: pathlib.Path | str):
        self.proposal_path = pathlib.Path(proposal_path)

    def propose(self, context: Mapping[str, Any]) -> ProjectProposal:
        value = json.loads(self.proposal_path.read_text(encoding="utf-8"))
        proposal = ProjectProposal.from_dict(value)
        if proposal.project_id != str(context.get("project_id", proposal.project_id)):
            raise ValueError("proposal project_id does not match the current project")
        return proposal


class EmbeddedProjectAgent:
    """Adapter from the existing AgentComposer to the ProjectAgent interface.

    It still goes through the same admission call. The embedded planner is a
    fallback, not a privileged path.
    """

    def __init__(self, composer: Any):
        self.composer = composer

    def propose(self, context: Any) -> ProjectProposal:
        decision = self.composer.decide(context)
        operations = []
        for edit in decision.edits:
            payload = dict(edit.payload)
            config = dict(payload.get("config") or {})
            operations.append({
                "operation": edit.operation, "node_id": edit.node_id,
                "capability_ref": payload.get("capability_ref", ""),
                "parent_id": payload.get("parent_id", ""),
                "depends_on": list(payload.get("depends_on") or edit.payload.get("depends_on") or ()),
                "config": config,
            })
        return ProjectProposal(
            proposal_id=getattr(decision, "decision_id", "embedded-decision"),
            project_id=str(getattr(context, "project_id", "project")),
            base_tree_version=int(context.project_intent.get("tree_version", 0))
            if isinstance(getattr(context, "project_intent", None), Mapping) else 0,
            goal_reference=str(getattr(context, "goal", "")),
            observed_evidence_refs=tuple(str(x) for x in
                                         (getattr(context, "failure_details", {}) or {}).get("evidence_refs", ())),
            proposed_operations=tuple(operations),
            requested_capability="",
            repair_strategy=getattr(decision, "summary", ""),
            resource_preference="embedded-planner",
            expected_progress=getattr(decision, "summary", ""),
            reason_summary=getattr(decision, "reason", "") or getattr(decision, "summary", ""),
        )


def _canonical_capabilities(catalog: Mapping[str, Any]) -> dict[str, str]:
    values = {}
    for capability, entry in catalog.items():
        contract = ((entry or {}).get("config") or {}).get("leaf_contract") or {}
        identity = str(contract.get("output_identity") or "")
        if identity:
            values[identity] = capability
        values.setdefault(capability, capability)
    return values


def _edit_from_operation(proposal: ProjectProposal, index: int, operation: Mapping[str, Any],
                         catalog: Mapping[str, Any]) -> TreeEdit:
    op = str(operation["operation"])
    node_id = str(operation["node_id"])
    payload = dict(operation.get("payload") or {})
    if op == "add_node":
        capability = str(operation.get("capability_ref") or payload.get("capability_ref") or "")
        depends_on = list(operation.get("depends_on") or payload.get("depends_on") or ())
        parent_id = str(operation.get("parent_id", payload.get("parent_id", "")))
        overrides = dict(operation.get("config") or payload.get("config") or {})
        entry = catalog.get(capability)
        if entry:
            merged = dict(entry.get("config") or {})
            merged.update(overrides)
            merged["executor_ref"] = entry.get("executor_ref", merged.get("executor_ref"))
            contract = dict(merged.get("leaf_contract") or {})
            if contract:
                contract["dependencies"] = depends_on
                merged["leaf_contract"] = contract
            overrides = merged
        payload = {"capability_ref": capability, "parent_id": parent_id,
                   "depends_on": depends_on, "config": overrides}
    elif op == "update_config":
        config = dict(operation.get("config") or payload.get("config") or {})
        payload = {"config": config}
    elif op == "retry_node":
        payload = {}
    elif op in {"add_dependency", "remove_dependency"}:
        payload = {"dependency": str(operation.get("dependency") or payload.get("dependency") or "")}
    elif op == "replace_executor":
        payload = {"executor_ref": str(operation.get("executor_ref") or payload.get("executor_ref") or "")}
    elif op == "replace_node":
        payload = {"capability_ref": str(operation.get("capability_ref") or payload.get("capability_ref") or ""),
                   "config": dict(operation.get("config") or payload.get("config") or {})}
    elif op == "move_node":
        payload = {"parent_id": str(operation.get("parent_id") or payload.get("parent_id") or "")}
    return TreeEdit(
        edit_id=f"{proposal.proposal_id}:{index:02d}", operation=op, node_id=node_id,
        payload=payload,
        provenance={"proposal_id": proposal.proposal_id,
                    "reason_summary": proposal.reason_summary,
                    "resource_preference": proposal.resource_preference},
    )


def admit_proposal(tree: CapabilityTree, current_tree_version: int,
                   proposal: ProjectProposal, *,
                   known_capabilities: set[str] | frozenset[str],
                   catalog: Mapping[str, Any],
                   policy: AdmissionPolicy | None = None) -> AdmissionResult:
    policy = policy or AdmissionPolicy()

    if policy.require_capability_contract or policy.capability_contracts or proposal.target_capability_id:
        from veriarbor.capability import CapabilityContract, GoalGap, admit_capability
        if not policy.project_id or proposal.project_id != policy.project_id:
            return AdmissionResult(False, 'PROJECT_SCOPE_REJECT', 'capability policy belongs to another project')
        contracts = {k: CapabilityContract(**v) for k, v in policy.capability_contracts.items()}
        gaps = {k: GoalGap(**v) for k, v in policy.goal_gaps.items()}
        claim = proposal.as_dict()
        # Resolve implementation identities from registered catalog metadata as well
        # as the proposal. A target claim cannot hide a forbidden implementation.
        strategies = set(proposal.strategy_capabilities)
        for operation in proposal.proposed_operations:
            ref = operation.get('capability_ref') or operation.get('payload', {}).get('capability_ref')
            existing = tree.by_id.get(operation['node_id'])
            ref = ref or (existing.capability_ref if existing else '')
            if ref:
                strategies.add(ref)
                strategies.update(catalog.get(ref, {}).get('implements_capabilities', ()))
        claim['strategy_capabilities'] = sorted(strategies)
        from veriarbor.model import Evidence
        inputs = []
        for operation in proposal.proposed_operations:
            for binding in policy.evidence_inputs.get(operation['node_id'], ()):
                if not binding.get('evidence'):
                    return AdmissionResult(False, 'PORT_EVIDENCE_SCOPE_REJECT', 'required input evidence missing')
                requirements = dict(binding['requirements'])
                requirements['required_scope'] = {**requirements.get('required_scope', {}), 'PROJECT': policy.project_id}
                inputs.append((Evidence(**binding['evidence']), requirements))
        code = admit_capability(claim, contracts, gaps, budget_allowed=policy.budget_state == 'OK', evidence_inputs=inputs)
        if code != 'ADMITTED':
            return AdmissionResult(False, code, 'capability proposal failed governance')

    if proposal.base_tree_version != current_tree_version:
        return AdmissionResult(False, "STALE_BASE_TREE_VERSION",
                               "proposal base_tree_version is not the current tree version",
                               {"requested": proposal.base_tree_version,
                                "current": current_tree_version})

    if len(proposal.proposed_operations) > policy.max_tree_edits:
        return AdmissionResult(False, "EDIT_LIMIT", "proposal exceeds the edit budget",
                               {"requested": len(proposal.proposed_operations),
                                "limit": policy.max_tree_edits})

    additions = [op for op in proposal.proposed_operations if op.get("operation") == "add_node"]
    if policy.incremental_mode and len(additions) > policy.max_new_nodes:
        return AdmissionResult(False, "INCREMENTAL_LIMIT",
                               "incremental mode admits one frontier capability per proposal",
                               {"requested": len(additions), "limit": policy.max_new_nodes,
                                "operations": [op.get("node_id") for op in additions]})

    if policy.budget_state == "BLOCKED":
        wants_model = any(str(op.get("config", {}).get("executor_ref") or "").startswith("llm.")
                          or str(op.get("resource_preference") or "").startswith("model:")
                          for op in proposal.proposed_operations)
        if wants_model:
            return AdmissionResult(False, "BUDGET_BLOCKED",
                                   "no new model resource may be admitted while budget is blocked",
                                   {"resource_preference": proposal.resource_preference})

    canonical = _canonical_capabilities(catalog)
    edits = []
    try:
        for index, operation in enumerate(proposal.proposed_operations):
            op = str(operation["operation"])
            capability = str(operation.get("capability_ref") or "")
            if op == "add_node" and capability and capability not in known_capabilities:
                suggestion = canonical.get(capability, "")
                return AdmissionResult(False, "UNKNOWN_CAPABILITY",
                                       "capability is not registered in the current catalog",
                                       {"requested": capability,
                                        "canonical": suggestion or "UNKNOWN"})
            edit = _edit_from_operation(proposal, index, operation, catalog)
            if op == "add_node":
                contract = dict(edit.payload.get("config", {}).get("leaf_contract") or {})
                if policy.require_leaf_contract and not contract:
                    return AdmissionResult(False, "MISSING_LEAF_CONTRACT",
                                           "add_node requires a leaf contract", {"node_id": edit.node_id})
                effects = set(contract.get("effect_domains") or ())
                remote = effects & REMOTE_EFFECTS
                if remote and not policy.allow_remote_effects:
                    return AdmissionResult(False, "UNAUTHORIZED_EFFECT",
                                           "remote external effects are not admitted",
                                           {"node_id": edit.node_id, "effects": sorted(remote)})
                if not effects:
                    return AdmissionResult(False, "MISSING_EFFECT",
                                           "a leaf must declare its effect domain", {"node_id": edit.node_id})
                extra = effects - policy.allowed_effect_domains - REMOTE_EFFECTS
                if extra:
                    return AdmissionResult(False, "UNAUTHORIZED_EFFECT",
                                           "effect domain is outside the admitted set",
                                           {"node_id": edit.node_id, "effects": sorted(extra)})
                if contract.get("task_kind") in WRITING_KINDS and not contract.get("acceptance"):
                    return AdmissionResult(False, "MISSING_ACCEPTANCE",
                                           "writing leaves require an acceptance obligation",
                                           {"node_id": edit.node_id})
                try:
                    validate_leaf(type("Preview", (), {
                        "id": edit.node_id, "executable": True,
                        "config": {"executor_ref": edit.payload["config"].get("executor_ref"),
                                   "leaf_contract": contract},
                        "depends_on": tuple(edit.payload.get("depends_on") or ()),
                    })())
                except Exception as exc:  # noqa: BLE001 - report exact contract failure
                    return AdmissionResult(False, "INVALID_LEAF_CONTRACT", str(exc),
                                           {"node_id": edit.node_id})
            edits.append(edit)
        proposed = apply_tree_edits(tree, tuple(edits), known_capabilities=known_capabilities)
    except ValueError as exc:
        message = str(exc)
        code = "INVALID_TREE_EDIT"
        details: dict[str, Any] = {"error": message}
        if "node already exists" in message:
            code = "DUPLICATE_NODE"
        elif "node does not exist" in message:
            code = "UNKNOWN_NODE"
        elif "dependency" in message or "unknown_dependency" in message:
            code = "INVALID_DEPENDENCY"
            details["dependency"] = _extract_dependency(message)
        elif "unknown capability" in message:
            code = "UNKNOWN_CAPABILITY"
        return AdmissionResult(False, code, message, details)

    return AdmissionResult(True, "ADMITTED", "proposal admitted",
                           {"tree_edits": len(edits),
                            "incremental": policy.incremental_mode}, tuple(edits), proposed)


def _extract_dependency(message: str) -> str:
    for marker in ("unknown_dependency:", "dependency does not exist"):
        if marker in message:
            return message.split(marker, 1)[-1].strip(" :")
    return ""


def load_proposal(path: pathlib.Path | str) -> ProjectProposal:
    return ProjectProposal.from_dict(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))


__all__ = [
    "PROPOSAL_KIND", "PROPOSAL_SCHEMA_VERSION", "ProjectProposal", "ProjectRoadmap",
    "RoadmapItem", "AdmissionPolicy", "AdmissionResult", "ProjectAgent",
    "ExternalFileProjectAgent", "EmbeddedProjectAgent", "admit_proposal", "load_proposal",
]
