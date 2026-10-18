from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


class CandidateRevisionStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    VALIDATING = "VALIDATING"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    ADMISSION_PENDING = "ADMISSION_PENDING"
    ADMITTED = "ADMITTED"
    INSTALLED = "INSTALLED"


class BuildLifecycleState(str, Enum):
    SPEC_READY = "SPEC_READY"
    ROUTE_FROZEN = "ROUTE_FROZEN"
    GENERATION_REQUESTED = "GENERATION_REQUESTED"
    PROVIDER_BLOCKED = "PROVIDER_BLOCKED"
    CANDIDATE_CREATED = "CANDIDATE_CREATED"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    VALIDATING = "VALIDATING"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    REPAIR_REQUESTED = "REPAIR_REQUESTED"
    ADMISSION_PENDING = "ADMISSION_PENDING"
    ADMITTED = "ADMITTED"
    INSTALLED = "INSTALLED"
    RESUMED = "RESUMED"
    REJECTED = "REJECTED"
    BLOCKED_FRAMEWORK = "BLOCKED_FRAMEWORK"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ValidationPhase(str, Enum):
    SYNTAX = "SYNTAX"
    SCOPE = "SCOPE"
    INTERFACE = "INTERFACE"
    CONTRACT_TEST = "CONTRACT_TEST"
    DEPENDENCY = "DEPENDENCY"
    RISK = "RISK"
    SECURITY = "SECURITY"
    RUNTIME_EXAMPLE = "RUNTIME_EXAMPLE"
    SERIALIZATION = "SERIALIZATION"
    EXTERNAL_SMOKE = "EXTERNAL_SMOKE"
    ADMISSION = "ADMISSION"


class FailureDomain(str, Enum):
    CANDIDATE_DEFECT = "CANDIDATE_DEFECT"
    CANDIDATE_POLICY_DEFECT = "CANDIDATE_POLICY_DEFECT"
    FRAMEWORK_VALIDATOR_DEFECT = "FRAMEWORK_VALIDATOR_DEFECT"
    FRAMEWORK_HARNESS_DEFECT = "FRAMEWORK_HARNESS_DEFECT"
    PROVIDER_TRANSPORT_FAILURE = "PROVIDER_TRANSPORT_FAILURE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_SCHEMA_FAILURE = "PROVIDER_SCHEMA_FAILURE"
    EXTERNAL_DEPENDENCY_FAILURE = "EXTERNAL_DEPENDENCY_FAILURE"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    DEPENDENCY_DRIFT = "DEPENDENCY_DRIFT"
    CONTRACT_GAP = "CONTRACT_GAP"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class FailureOwner(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATOR = "VALIDATOR"
    HARNESS = "HARNESS"
    PROVIDER = "PROVIDER"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    ENVIRONMENT = "ENVIRONMENT"
    DEPENDENCY = "DEPENDENCY"
    CONTRACT = "CONTRACT"
    UNKNOWN = "UNKNOWN"


class RecommendedAction(str, Enum):
    REVALIDATE_EXISTING = "REVALIDATE_EXISTING"
    REPAIR_CANDIDATE = "REPAIR_CANDIDATE"
    RETRY_GENERATION = "RETRY_GENERATION"
    RETRY_TRANSPORT = "RETRY_TRANSPORT"
    WAIT_EXTERNAL = "WAIT_EXTERNAL"
    BLOCK_ENVIRONMENT = "BLOCK_ENVIRONMENT"
    REJECT_CANDIDATE = "REJECT_CANDIDATE"
    ADMIT_CANDIDATE = "ADMIT_CANDIDATE"
    REVALIDATE_DEPENDENCY = "REVALIDATE_DEPENDENCY"
    ESCALATE_REVIEW = "ESCALATE_REVIEW"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class CandidateRevision:
    revision_id: str
    capability_ref: str
    build_run_id: str
    revision_number: int
    parent_revision_id: str | None
    spec_hash: str
    route_snapshot_hash: str
    provider_id: str
    provider_request_id: str
    provider_response_id: str
    provider_operation: str
    source_manifest: tuple[Mapping[str, Any], ...]
    source_hash: str
    package_hash: str
    created_at: str
    creation_reason: str
    status: CandidateRevisionStatus = CandidateRevisionStatus.CREATED
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.revision_number < 1 or not self.revision_id or not self.capability_ref:
            raise ValueError("candidate revision identity is invalid")
        object.__setattr__(self, "source_manifest", tuple(_freeze(row) for row in self.source_manifest))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CandidateRevision", "schema_version": self.schema_version,
            "revision_id": self.revision_id, "capability_ref": self.capability_ref,
            "build_run_id": self.build_run_id, "revision_number": self.revision_number,
            "parent_revision_id": self.parent_revision_id, "spec_hash": self.spec_hash,
            "route_snapshot_hash": self.route_snapshot_hash, "provider_id": self.provider_id,
            "provider_request_id": self.provider_request_id, "provider_response_id": self.provider_response_id,
            "provider_operation": self.provider_operation, "source_manifest": _thaw(self.source_manifest),
            "source_hash": self.source_hash, "package_hash": self.package_hash,
            "created_at": self.created_at, "creation_reason": self.creation_reason,
            "status": self.status.value, "contains_credentials": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateRevision":
        if value.get("kind") != "CandidateRevision" or value.get("schema_version") != "1.0":
            raise ValueError("unsupported candidate revision")
        return cls(
            str(value["revision_id"]), str(value["capability_ref"]), str(value["build_run_id"]),
            int(value["revision_number"]), value.get("parent_revision_id"), str(value["spec_hash"]),
            str(value["route_snapshot_hash"]), str(value["provider_id"]), str(value.get("provider_request_id", "")),
            str(value.get("provider_response_id", "")), str(value["provider_operation"]),
            tuple(value.get("source_manifest", ())), str(value["source_hash"]), str(value["package_hash"]),
            str(value["created_at"]), str(value["creation_reason"]), CandidateRevisionStatus(str(value["status"])),
        )


@dataclass(frozen=True)
class ValidatorSuiteIdentity:
    validator_suite_id: str
    validator_suite_version: str
    validator_suite_hash: str
    validator_source_hashes: Mapping[str, str] = field(default_factory=dict)
    contract_test_hashes: Mapping[str, str] = field(default_factory=dict)
    fixture_hashes: Mapping[str, str] = field(default_factory=dict)
    policy_version: str = "1.0"
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "validator_source_hashes", _freeze(self.validator_source_hashes))
        object.__setattr__(self, "contract_test_hashes", _freeze(self.contract_test_hashes))
        object.__setattr__(self, "fixture_hashes", _freeze(self.fixture_hashes))

    def as_dict(self) -> dict[str, Any]:
        return {key: _thaw(value) for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class ValidationReceipt:
    validation_id: str
    candidate_revision_id: str
    candidate_source_hash: str
    spec_hash: str
    dependency_manifest_hash: str
    validator_suite_id: str
    validator_suite_hash: str
    validator_version: str
    validation_phase: ValidationPhase
    status: str
    failure_domain: FailureDomain | None
    failure_code: str
    failure_owner: FailureOwner | None
    expected: Any
    observed: Any
    evidence_refs: tuple[str, ...]
    recommended_action: RecommendedAction
    started_at: str
    ended_at: str
    duration_ms: int
    receipt_hash: str
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ValidationReceipt", "schema_version": self.schema_version,
            **{key: _thaw(value) for key, value in self.__dict__.items() if key != "schema_version"},
            "validation_phase": self.validation_phase.value,
            "failure_domain": self.failure_domain.value if self.failure_domain else None,
            "failure_owner": self.failure_owner.value if self.failure_owner else None,
            "recommended_action": self.recommended_action.value,
            "contains_credentials": False,
        }


@dataclass(frozen=True)
class ProviderAttemptReceipt:
    attempt_id: str
    operation: str
    provider_id: str
    model: str
    request_id: str
    response_id: str
    route_snapshot_hash: str
    started_at: str
    ended_at: str
    status: str
    error_class: str
    outcome_unknown: bool
    reserved_tokens: Mapping[str, Any]
    actual_tokens: Mapping[str, Any]
    cost: Any
    candidate_revision_created: bool
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "reserved_tokens", _freeze(self.reserved_tokens))
        object.__setattr__(self, "actual_tokens", _freeze(self.actual_tokens))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ProviderAttemptReceipt", "schema_version": self.schema_version,
            **{key: _thaw(value) for key, value in self.__dict__.items() if key != "schema_version"},
            "contains_credentials": False,
        }


@dataclass(frozen=True)
class LifecycleTransition:
    from_state: BuildLifecycleState
    to_state: BuildLifecycleState
    reason: str
    evidence_refs: tuple[str, ...]
    actor: str
    timestamp: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_state.value, "to": self.to_state.value, "reason": self.reason,
            "evidence_refs": list(self.evidence_refs), "actor": self.actor, "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class ActionDecision:
    action: RecommendedAction
    target_state: BuildLifecycleState
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"action": self.action.value, "target_state": self.target_state.value, "reason": self.reason}
