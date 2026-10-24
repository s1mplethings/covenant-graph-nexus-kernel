from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CapabilityEffect(str, Enum):
    READ_ONLY = "READ_ONLY"
    WRITE_KNOWLEDGE = "WRITE_KNOWLEDGE"
    WRITE_CODE = "WRITE_CODE"
    EXTERNAL_ACTION = "EXTERNAL_ACTION"
    MAINTENANCE = "MAINTENANCE"
    EVALUATION = "EVALUATION"
    SYSTEM = "SYSTEM"


class DecisionLevel(str, Enum):
    DETERMINISTIC = "L0_DETERMINISTIC"
    CHEAP_MODEL = "L1_CHEAP_MODEL"
    STRONG_MODEL = "L2_STRONG_MODEL"
    HUMAN_STOP = "L3_HUMAN_STOP"


class DecisionRiskClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    SCOPE_TOO_WIDE = "SCOPE_TOO_WIDE"
    NO_PROGRESS = "NO_PROGRESS"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


@dataclass(frozen=True)
class CapabilitySearchRequest:
    goal: str
    available_inputs: tuple[str, ...] = ()
    allowed_effects: tuple[CapabilityEffect, ...] = (CapabilityEffect.READ_ONLY,)
    permissions: tuple[str, ...] = ()
    available_state: tuple[str, ...] = ()
    allowed_scope: tuple[str, ...] = ()
    requested_version: str | None = None
    exact_ref: str | None = None
    require_qualified: bool = True
    top_k: int = 3

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("capability search goal is required")
        if not 1 <= self.top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        for name in ("available_inputs", "permissions", "available_state", "allowed_scope"):
            object.__setattr__(self, name, tuple(dict.fromkeys(str(item).strip() for item in getattr(self, name) if str(item).strip())))
        object.__setattr__(self, "allowed_effects", tuple(dict.fromkeys(CapabilityEffect(item) for item in self.allowed_effects)))


@dataclass(frozen=True)
class CapabilityCandidate:
    capability_ref: str
    score: float
    effect: CapabilityEffect
    purpose: str
    executor_ref: str
    qualification: str
    context: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_ref": self.capability_ref,
            "score": self.score,
            "effect": self.effect.value,
            "purpose": self.purpose,
            "executor_ref": self.executor_ref,
            "qualification": self.qualification,
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class CapabilitySearchResult:
    candidates: tuple[CapabilityCandidate, ...]
    eligible_count: int
    retrieval_pool_count: int
    total_count: int
    rejected: Mapping[str, tuple[str, ...]]
    full_registry_context_tokens: int
    topk_context_tokens: int
    index_hash: str
    policy_hash: str
    latency_ms: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "rejected", MappingProxyType({str(key): tuple(value) for key, value in self.rejected.items()}))

    @property
    def status(self) -> str:
        return "PASS" if self.candidates else "NO_ELIGIBLE_CAPABILITY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CapabilitySearchResult",
            "schema_version": "1.0",
            "status": self.status,
            "candidates": [item.as_dict() for item in self.candidates],
            "eligible_count": self.eligible_count,
            "retrieval_pool_count": self.retrieval_pool_count,
            "total_count": self.total_count,
            "rejected": {key: list(value) for key, value in self.rejected.items()},
            "full_registry_context_tokens": self.full_registry_context_tokens,
            "topk_context_tokens": self.topk_context_tokens,
            "index_hash": self.index_hash,
            "policy_hash": self.policy_hash,
            "latency_ms": self.latency_ms,
            "authority": "CapabilityRegistry",
            "index_authority": False,
        }


@dataclass(frozen=True)
class DecisionContext:
    operation: str
    uncertainty: float = 0.0
    impact: DecisionRiskClass = DecisionRiskClass.LOW
    reversible: bool = True
    authority_scope: str = "LOCAL"
    evidence_sufficient: bool = True
    candidate_count: int = 1
    capability_qualified: bool = True
    validator_available: bool = True
    cheap_route_qualified: bool = True
    deterministic_rule_available: bool = False
    deterministic_evidence_valid: bool = False
    crosses_authority_boundary: bool = False
    critical_boundaries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("decision operation is required")
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("uncertainty must be between zero and one")
        if self.candidate_count < 0:
            raise ValueError("candidate_count cannot be negative")
        object.__setattr__(self, "critical_boundaries", tuple(sorted(set(self.critical_boundaries))))


@dataclass(frozen=True)
class DecisionRisk:
    risk_class: DecisionRiskClass
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"risk_class": self.risk_class.value, "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True)
class DecisionRoute:
    level: DecisionLevel
    action: str
    risk: DecisionRisk
    reason_codes: tuple[str, ...]
    escalation_from: DecisionLevel | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "DecisionRoute",
            "schema_version": "1.0",
            "level": self.level.value,
            "action": self.action,
            "risk": self.risk.as_dict(),
            "reason_codes": list(self.reason_codes),
            "escalation_from": self.escalation_from.value if self.escalation_from else None,
            "self_reported_confidence_authority": False,
        }


@dataclass(frozen=True)
class ValidationOutcome:
    status: ValidationStatus
    failure_fingerprint: str = ""
    repeat_count: int = 0

    def __post_init__(self) -> None:
        if self.repeat_count < 0:
            raise ValueError("repeat_count cannot be negative")
        if self.repeat_count and not self.failure_fingerprint:
            raise ValueError("repeated validation failure requires a fingerprint")

