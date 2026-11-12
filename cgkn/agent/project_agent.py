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

from cgkn.orchestration.admission import (
    PROPOSAL_KIND, PROPOSAL_SCHEMA_VERSION, WRITING_KINDS, REMOTE_EFFECTS,
    ProjectProposal, RoadmapItem, ProjectRoadmap, AdmissionPolicy, AdmissionResult,
    admit_proposal, _digest, _canonical_capabilities, _edit_from_operation,
    _extract_dependency,
)


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


def load_proposal(path: pathlib.Path | str) -> ProjectProposal:
    return ProjectProposal.from_dict(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))


__all__ = [
    "PROPOSAL_KIND", "PROPOSAL_SCHEMA_VERSION", "ProjectProposal", "ProjectRoadmap",
    "RoadmapItem", "AdmissionPolicy", "AdmissionResult", "ProjectAgent",
    "ExternalFileProjectAgent", "EmbeddedProjectAgent", "admit_proposal", "load_proposal",
]
