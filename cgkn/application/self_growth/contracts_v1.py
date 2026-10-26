from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class GapClass(str, Enum):
    NO_GAP_EXISTING_CAPABILITY = "NO_GAP_EXISTING_CAPABILITY"
    COMPOSITION_GAP = "COMPOSITION_GAP"
    PARAMETERIZATION_GAP = "PARAMETERIZATION_GAP"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    EVIDENCE_GAP = "EVIDENCE_GAP"
    PERMISSION_GAP = "PERMISSION_GAP"
    STATE_GAP = "STATE_GAP"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    EXISTING_CAPABILITY_BUG = "EXISTING_CAPABILITY_BUG"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    PRODUCT_DIRECTION_GAP = "PRODUCT_DIRECTION_GAP"
    AUTHORITY_CHANGE_REQUIRED = "AUTHORITY_CHANGE_REQUIRED"
    CORE_EXTENSION_REQUIRED = "CORE_EXTENSION_REQUIRED"
    UNRESOLVED = "UNRESOLVED"


class GrowthLifecycle(str, Enum):
    OBSERVED = "OBSERVED"
    CLASSIFIED = "CLASSIFIED"
    SEARCHED = "SEARCHED"
    COMPOSITION_ATTEMPTED = "COMPOSITION_ATTEMPTED"
    GAP_CONFIRMED = "GAP_CONFIRMED"
    PROPOSED = "PROPOSED"
    SANDBOX_IMPLEMENTED = "SANDBOX_IMPLEMENTED"
    VALIDATED = "VALIDATED"
    QUALIFIED = "QUALIFIED"
    EXPERIMENTALLY_ADMITTED = "EXPERIMENTALLY_ADMITTED"
    REJECTED = "REJECTED"
    DEPRECATED_CANDIDATE = "DEPRECATED_CANDIDATE"


class EffectTier(str, Enum):
    PURE = "PURE"
    READ_LOCAL = "READ_LOCAL"
    WRITE_LOCAL_SANDBOX = "WRITE_LOCAL_SANDBOX"
    WRITE_PROJECT_SCOPED = "WRITE_PROJECT_SCOPED"
    WRITE_KNOWLEDGE = "WRITE_KNOWLEDGE"
    EXTERNAL_READ = "EXTERNAL_READ"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    SYSTEM = "SYSTEM"


class QualificationLevel(str, Enum):
    SANDBOX_VALID = "SANDBOX_VALID"
    PROVISIONAL = "PROVISIONAL"
    QUALIFIED = "QUALIFIED"
    EXPERIMENTALLY_ADMITTED = "EXPERIMENTALLY_ADMITTED"


class GrowthGroup(str, Enum):
    G0 = "G0_FROZEN_REGISTRY"
    G1 = "G1_NAIVE_GROWTH"
    G2 = "G2_SEARCH_COMPOSE_CREATE"
    G3 = "G3_HIERARCHICAL_SELF_GROWTH"


class ResolutionKind(str, Enum):
    DIRECT_REUSE = "DIRECT_REUSE"
    PARAMETERIZATION = "PARAMETERIZATION"
    COMPOSITION = "COMPOSITION"
    CREATE = "CREATE"
    REPAIR_EXISTING = "REPAIR_EXISTING"
    NON_CAPABILITY_PATH = "NON_CAPABILITY_PATH"
    CRITICAL_STOP = "CRITICAL_STOP"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class GrowthTaskNeed:
    task_id: str
    goal: str
    family: str
    input_semantics: str
    output_semantics: str
    effect: EffectTier = EffectTier.PURE
    scope: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    available_state: tuple[str, ...] = ()
    required_state: tuple[str, ...] = ()
    requested_capability_ref: str | None = None
    parameter_variant: str = ""
    failure_signal: str = ""
    critical_boundary: str = ""
    required_observable: str = ""
    composition_goal: tuple[str, ...] = ()
    abstraction_choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.goal.strip() or not self.family.strip():
            raise ValueError("task id, goal, and family are required")
        for name in (
            "scope", "permissions", "available_state", "required_state",
            "composition_goal", "abstraction_choices",
        ):
            object.__setattr__(self, name, tuple(str(item) for item in getattr(self, name)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "family": self.family,
            "input_semantics": self.input_semantics,
            "output_semantics": self.output_semantics,
            "effect": self.effect.value,
            "scope": list(self.scope),
            "permissions": list(self.permissions),
            "available_state": list(self.available_state),
            "required_state": list(self.required_state),
            "requested_capability_ref": self.requested_capability_ref,
            "parameter_variant": self.parameter_variant,
            "failure_signal": self.failure_signal,
            "critical_boundary": self.critical_boundary,
            "required_observable": self.required_observable,
            "composition_goal": list(self.composition_goal),
            "abstraction_choices": list(self.abstraction_choices),
        }


@dataclass(frozen=True)
class CompositionPlan:
    capability_refs: tuple[str, ...]
    depth: int
    input_semantics: str
    output_semantics: str
    estimated_cost_units: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_refs", tuple(self.capability_refs))
        if self.depth != len(self.capability_refs) or not 1 <= self.depth <= 4:
            raise ValueError("composition depth must match a bounded plan")

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_refs": list(self.capability_refs),
            "depth": self.depth,
            "input_semantics": self.input_semantics,
            "output_semantics": self.output_semantics,
            "estimated_cost_units": self.estimated_cost_units,
            "authority": "ephemeral_execution_plan",
        }


@dataclass(frozen=True)
class GrowthClassification:
    gap_class: GapClass
    reason_codes: tuple[str, ...]
    searched: bool
    top_k_refs: tuple[str, ...] = ()
    selected_ref: str | None = None
    composition: CompositionPlan | None = None
    search_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "top_k_refs", tuple(self.top_k_refs))
        object.__setattr__(self, "search_evidence", MappingProxyType(dict(self.search_evidence)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "gap_class": self.gap_class.value,
            "reason_codes": list(self.reason_codes),
            "searched": self.searched,
            "top_k_refs": list(self.top_k_refs),
            "selected_ref": self.selected_ref,
            "composition": self.composition.as_dict() if self.composition else None,
            "search_evidence": dict(self.search_evidence),
        }


@dataclass(frozen=True)
class CapabilityProposal:
    candidate_id: str
    capability_id: str
    version: str
    purpose: str
    abstraction_boundary: str
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    effect_class: EffectTier
    required_permissions: tuple[str, ...]
    required_state: tuple[str, ...]
    side_effects: tuple[str, ...]
    failure_semantics: tuple[str, ...]
    scope: tuple[str, ...]
    existing_overlapping_capabilities: tuple[str, ...]
    why_composition_is_insufficient: str
    expected_reuse_scope: tuple[str, ...]
    qualification_plan: tuple[str, ...]
    security_constraints: tuple[str, ...]
    allowed_paths: tuple[str, ...] = ("executor.py",)
    forbidden_paths: tuple[str, ...] = ()
    required_interfaces: tuple[str, ...] = ("execute(value)",)
    dependency_policy: str = "stdlib_or_existing_only"
    effect_policy: str = "declared_effect_only"

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.capability_id or not self.purpose:
            raise ValueError("proposal identity and purpose are required")
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", self.capability_id):
            raise ValueError("capability identity must be canonical")
        if not re.fullmatch(r"[1-9][0-9]*", self.version):
            raise ValueError("capability version must be a positive integer")
        object.__setattr__(self, "input_contract", MappingProxyType(dict(self.input_contract)))
        object.__setattr__(self, "output_contract", MappingProxyType(dict(self.output_contract)))
        for name in (
            "required_permissions", "required_state", "side_effects", "failure_semantics",
            "scope", "existing_overlapping_capabilities", "expected_reuse_scope",
            "qualification_plan", "security_constraints", "allowed_paths", "forbidden_paths",
            "required_interfaces",
        ):
            object.__setattr__(self, name, tuple(str(item) for item in getattr(self, name)))
        if self.effect_class not in {EffectTier.PURE, EffectTier.READ_LOCAL, EffectTier.WRITE_LOCAL_SANDBOX}:
            raise ValueError("proposal effect is not eligible for automatic experimental admission")
        for raw in (*self.allowed_paths, *self.forbidden_paths):
            normalized = raw.replace("\\", "/")
            if not normalized or normalized.startswith(("/", "~")) or ":" in normalized or ".." in normalized.split("/"):
                raise ValueError("proposal paths must remain relative and traversal-free")

    @property
    def ref(self) -> str:
        return f"{self.capability_id}@{self.version}"

    @property
    def semantic_signature(self) -> str:
        return canonical_hash({
            "purpose": " ".join(self.purpose.lower().split()),
            "input_semantics": self.input_contract.get("semantic_type", self.input_contract),
            "output_semantics": self.output_contract.get("semantic_type", self.output_contract),
            "effect": self.effect_class.value,
            "scope": sorted(self.scope),
        })

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "capability_id": self.capability_id,
            "version": self.version,
            "purpose": self.purpose,
            "abstraction_boundary": self.abstraction_boundary,
            "input_contract": dict(self.input_contract),
            "output_contract": dict(self.output_contract),
            "effect_class": self.effect_class.value,
            "required_permissions": list(self.required_permissions),
            "required_state": list(self.required_state),
            "side_effects": list(self.side_effects),
            "failure_semantics": list(self.failure_semantics),
            "scope": list(self.scope),
            "existing_overlapping_capabilities": list(self.existing_overlapping_capabilities),
            "why_composition_is_insufficient": self.why_composition_is_insufficient,
            "expected_reuse_scope": list(self.expected_reuse_scope),
            "qualification_plan": list(self.qualification_plan),
            "security_constraints": list(self.security_constraints),
            "allowed_paths": list(self.allowed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "required_interfaces": list(self.required_interfaces),
            "dependency_policy": self.dependency_policy,
            "effect_policy": self.effect_policy,
            "semantic_signature": self.semantic_signature,
        }


@dataclass(frozen=True)
class StrongDecisionPacket:
    task_need: Mapping[str, Any]
    gap_classification_evidence: Mapping[str, Any]
    top_k_capabilities: tuple[Mapping[str, Any], ...]
    failed_composition_attempts: tuple[Mapping[str, Any], ...]
    required_observable_result: str
    impact_risk: str
    candidate_abstraction_choices: tuple[str, ...]
    public_constraints: tuple[str, ...]
    full_possible_context_chars: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_need", MappingProxyType(dict(self.task_need)))
        object.__setattr__(self, "gap_classification_evidence", MappingProxyType(dict(self.gap_classification_evidence)))
        object.__setattr__(self, "top_k_capabilities", tuple(MappingProxyType(dict(item)) for item in self.top_k_capabilities))
        object.__setattr__(self, "failed_composition_attempts", tuple(MappingProxyType(dict(item)) for item in self.failed_composition_attempts))
        object.__setattr__(self, "candidate_abstraction_choices", tuple(self.candidate_abstraction_choices))
        object.__setattr__(self, "public_constraints", tuple(self.public_constraints))

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_need": dict(self.task_need),
            "gap_classification_evidence": dict(self.gap_classification_evidence),
            "top_k_capabilities": [dict(item) for item in self.top_k_capabilities],
            "failed_composition_attempts": [dict(item) for item in self.failed_composition_attempts],
            "required_observable_result": self.required_observable_result,
            "impact_risk": self.impact_risk,
            "candidate_abstraction_choices": list(self.candidate_abstraction_choices),
            "public_constraints": list(self.public_constraints),
        }

    @property
    def actual_context_chars(self) -> int:
        return len(json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    @property
    def reduction_ratio(self) -> float:
        if self.full_possible_context_chars <= 0:
            return 0.0
        return 1.0 - (self.actual_context_chars / self.full_possible_context_chars)


@dataclass(frozen=True)
class QualificationReceipt:
    candidate_id: str
    capability_ref: str
    level: QualificationLevel
    status: str
    checks: Mapping[str, bool]
    hidden_case_count: int
    hidden_pass_count: int
    source_hash: str
    contract_hash: str
    receipt_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
        expected = canonical_hash({
            "candidate_id": self.candidate_id,
            "capability_ref": self.capability_ref,
            "level": self.level.value,
            "status": self.status,
            "checks": dict(self.checks),
            "hidden_case_count": self.hidden_case_count,
            "hidden_pass_count": self.hidden_pass_count,
            "source_hash": self.source_hash,
            "contract_hash": self.contract_hash,
        })
        if self.receipt_hash and self.receipt_hash != expected:
            raise ValueError("qualification receipt hash mismatch")
        object.__setattr__(self, "receipt_hash", expected)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "capability_ref": self.capability_ref,
            "level": self.level.value,
            "status": self.status,
            "checks": dict(self.checks),
            "hidden_case_count": self.hidden_case_count,
            "hidden_pass_count": self.hidden_pass_count,
            "source_hash": self.source_hash,
            "contract_hash": self.contract_hash,
            "receipt_hash": self.receipt_hash,
        }

