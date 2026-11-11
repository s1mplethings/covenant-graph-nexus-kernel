"""Project-isolated capability registry and bindings.

A Project Tree never inherits another project's tree, version, acceptance,
budget or UNKNOWN state. Projects may bind independently registered generic
capabilities. Registry history is eligibility evidence, never project PASS.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegistryEntry:
    capability_id: str
    version: str
    implementation_ref: str
    input_contract: tuple[str, ...]
    output_contract: tuple[str, ...]
    effects: tuple[str, ...]
    origin_project: str
    provenance: Mapping[str, Any]
    reuse_conditions: tuple[str, ...]
    known_limitations: tuple[str, ...] = ()
    evidence_summary: tuple[str, ...] = ()
    generic_responsibility: bool = False
    status: str = "REGISTERED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id, "version": self.version,
            "implementation_ref": self.implementation_ref,
            "input_contract": list(self.input_contract),
            "output_contract": list(self.output_contract),
            "effects": list(self.effects), "origin_project": self.origin_project,
            "provenance": dict(self.provenance),
            "reuse_conditions": list(self.reuse_conditions),
            "known_limitations": list(self.known_limitations),
            "evidence_summary": list(self.evidence_summary),
            "generic_responsibility": self.generic_responsibility,
            "status": self.status,
            "entry_sha256": _digest(self.as_dict_without_hash()),
        }

    def as_dict_without_hash(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id, "version": self.version,
            "implementation_ref": self.implementation_ref,
            "input_contract": list(self.input_contract),
            "output_contract": list(self.output_contract),
            "effects": list(self.effects), "origin_project": self.origin_project,
            "provenance": dict(self.provenance),
            "reuse_conditions": list(self.reuse_conditions),
            "known_limitations": list(self.known_limitations),
            "evidence_summary": list(self.evidence_summary),
            "generic_responsibility": self.generic_responsibility,
            "status": self.status,
        }


@dataclass(frozen=True)
class ProjectCapabilityBinding:
    project_id: str
    project_node_id: str
    capability_id: str
    capability_version: str
    local_consumer: str
    local_context: Mapping[str, Any]
    adapter: str = ""
    local_verification_scope: tuple[str, ...] = ()
    local_evidence: tuple[str, ...] = ()
    binding_status: str = "BOUND"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "project_node_id": self.project_node_id,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "local_consumer": self.local_consumer,
            "local_context": dict(self.local_context), "adapter": self.adapter,
            "local_verification_scope": list(self.local_verification_scope),
            "local_evidence": list(self.local_evidence),
            "binding_status": self.binding_status, "created_at": self.created_at,
        }


class SharedCapabilityRegistry:
    """Generic capabilities only. No project goal, tree or acceptance state."""

    def __init__(self, entries: dict[tuple[str, str], RegistryEntry] | None = None):
        self.entries = dict(entries or {})
        self.events: list[dict[str, Any]] = []

    def admit_candidate(self, candidate: RegistryEntry) -> tuple[bool, str, dict[str, Any]]:
        reasons = []
        if not candidate.capability_id or not candidate.version:
            reasons.append("missing identity/version")
        if not candidate.implementation_ref:
            reasons.append("missing implementation_ref")
        if not candidate.input_contract or not candidate.output_contract:
            reasons.append("missing input/output contract")
        if not candidate.effects:
            reasons.append("missing effects")
        if not candidate.origin_project:
            reasons.append("missing origin_project")
        if not candidate.reuse_conditions:
            reasons.append("missing reuse_conditions")
        if not candidate.generic_responsibility:
            reasons.append("responsibility is not generic")
        if any("project" in effect and "project" not in candidate.capability_id for effect in candidate.effects):
            reasons.append("project-specific effect leaked into a generic entry")
        if reasons:
            self.events.append({"event": "REGISTRY_REJECTED", "capability_id": candidate.capability_id,
                                "reasons": reasons})
            return False, "REJECTED", {"reasons": reasons}
        key = (candidate.capability_id, candidate.version)
        if key in self.entries and self.entries[key].status == "REGISTERED":
            self.events.append({"event": "REGISTRY_DUPLICATE", "capability_id": candidate.capability_id})
            return False, "DUPLICATE", {"existing": self.entries[key].as_dict()}
        self.entries[key] = candidate
        self.events.append({"event": "REGISTRY_ADMITTED", "capability_id": candidate.capability_id,
                            "version": candidate.version, "origin_project": candidate.origin_project})
        return True, "REGISTERED", candidate.as_dict()

    def resolve(self, capability_id: str, version: str | None = None) -> RegistryEntry:
        if version:
            return self.entries[(capability_id, version)]
        matches = [e for (cid, _), e in self.entries.items() if cid == capability_id and e.status == "REGISTERED"]
        if not matches:
            raise KeyError(capability_id)
        return sorted(matches, key=lambda e: e.version)[-1]

    def bind(self, *, project_id: str, project_node_id: str, capability_id: str,
             version: str, local_consumer: str, local_context: Mapping[str, Any],
             adapter: str = "", verification_scope: tuple[str, ...] = (),
             consumer_inputs: tuple[str, ...] = ()) -> ProjectCapabilityBinding:
        entry = self.resolve(capability_id, version)
        if not project_id or not project_node_id or not local_consumer:
            raise ValueError("binding requires project, node and consumer")
        if not verification_scope:
            raise ValueError("binding requires a project-local verification scope")
        if consumer_inputs and not set(consumer_inputs) <= set(entry.input_contract):
            raise ValueError("CAPABILITY_CONTEXT_MISMATCH: ADAPTER_REQUIRED")
        binding = ProjectCapabilityBinding(project_id, project_node_id, capability_id,
                                           entry.version, local_consumer, dict(local_context),
                                           adapter, tuple(verification_scope))
        self.events.append({"event": "PROJECT_CAPABILITY_BOUND", "binding": binding.as_dict()})
        return binding

    @staticmethod
    def verify_binding(binding: ProjectCapabilityBinding, local_evidence: tuple[str, ...],
                       *, foreign_project_pass_refs: tuple[str, ...] = ()) -> tuple[bool, str]:
        if binding.binding_status != "BOUND":
            return False, "BINDING_NOT_ACTIVE"
        if not local_evidence:
            return False, "LOCAL_EVIDENCE_REQUIRED"
        if any(ref in foreign_project_pass_refs for ref in local_evidence):
            return False, "FOREIGN_PROJECT_ACCEPTANCE_CANNOT_BE_PROJECT_PASS"
        if not set(local_evidence) <= set(binding.local_verification_scope):
            return False, "LOCAL_EVIDENCE_OUTSIDE_SCOPE"
        return True, "LOCAL_VERIFICATION_ACCEPTED"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "SharedCapabilityRegistry", "schema_version": "1.0",
                "entries": [e.as_dict() for e in self.entries.values()],
                "events": list(self.events),
                "note": "Registry holds generic capabilities only; project trees, goals, acceptance and budgets are separate."}

    def save(self, path: pathlib.Path | str) -> None:
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(path).write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")


@dataclass
class ProjectContext:
    """Project-local state. Never share these objects or values across projects."""
    project_id: str
    goal: str
    tree_version: int
    acceptance: dict[str, str] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=lambda: {"state": "OK", "spent_cny": 0.0})
    unknown: dict[str, str] = field(default_factory=dict)
    node_states: dict[str, str] = field(default_factory=dict)
    failure_count: int = 0

    def assert_no_inheritance_from(self, other: "ProjectContext") -> None:
        if self.project_id == other.project_id:
            return
        if self.tree_version == other.tree_version and self.node_states == other.node_states:
            raise ValueError("PROJECT_TREE_IDENTITY_MISMATCH: independent projects cannot share tree version and nodes")
        if self.acceptance is other.acceptance or self.budget is other.budget or self.unknown is other.unknown:
            raise ValueError("PROJECT_STATE_SHARED_BETWEEN_PROJECTS")


def load_registry(path: pathlib.Path | str) -> SharedCapabilityRegistry:
    value = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    entries = {}
    for raw in value.get("entries", []):
        entry = RegistryEntry(
            str(raw["capability_id"]), str(raw["version"]), str(raw["implementation_ref"]),
            tuple(raw.get("input_contract", ())), tuple(raw.get("output_contract", ())),
            tuple(raw.get("effects", ())), str(raw["origin_project"]),
            dict(raw.get("provenance", {})), tuple(raw.get("reuse_conditions", ())),
            tuple(raw.get("known_limitations", ())), tuple(raw.get("evidence_summary", ())),
            bool(raw.get("generic_responsibility", False)), str(raw.get("status", "REGISTERED")))
        entries[(entry.capability_id, entry.version)] = entry
    registry = SharedCapabilityRegistry(entries)
    registry.events = list(value.get("events", []))
    return registry


__all__ = ["RegistryEntry", "ProjectCapabilityBinding", "SharedCapabilityRegistry",
           "ProjectContext", "load_registry"]
