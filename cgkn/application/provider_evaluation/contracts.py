from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence


TASK_CLASSES = frozenset({
    "agent.composition",
    "worker.codegen",
    "worker.repair",
    "capability.build",
    "structured.output",
    "project.domain.simple",
    "project.domain.persistent",
    "project.domain.library",
    "repository.patch",
    "project.repair",
})
FAILURE_CLASSES = frozenset({
    "TRANSPORT_FAILURE",
    "SCHEMA_FAILURE",
    "TASK_FAILURE",
    "INTERFACE_FAILURE",
    "SCOPE_FAILURE",
    "REPAIR_FAILURE",
    "BUDGET_BLOCKED",
    "TIMEOUT",
    "NONE",
})


def canonical_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BenchmarkBudget:
    timeout_seconds: int
    max_input_tokens: int
    max_output_tokens: int
    max_estimated_cost: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.timeout_seconds <= 600:
            raise ValueError("benchmark timeout must be between 1 and 600 seconds")
        if self.max_input_tokens < 1 or self.max_output_tokens < 1:
            raise ValueError("benchmark token budgets must be positive")
        if self.max_estimated_cost is not None and self.max_estimated_cost < 0:
            raise ValueError("benchmark cost budget cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_estimated_cost": self.max_estimated_cost if self.max_estimated_cost is not None else "UNAVAILABLE",
        }


@dataclass(frozen=True)
class ProviderBenchmarkCase:
    case_id: str
    task_class: str
    role: str
    input_contract: Mapping[str, Any]
    expected_output_contract: Mapping[str, Any]
    budget: BenchmarkBudget
    timeout: int
    validation: Sequence[str]
    risk: str
    benchmark_version: str
    prompt_facts: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.case_id.strip() or self.task_class not in TASK_CLASSES:
            raise ValueError("benchmark case identity and supported task class are required")
        if self.role not in {"agent", "worker"}:
            raise ValueError("benchmark role must be agent or worker")
        if self.timeout != self.budget.timeout_seconds:
            raise ValueError("case timeout must equal its budget timeout")
        if not self.validation or not self.benchmark_version.strip():
            raise ValueError("benchmark validation and version are required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "task_class": self.task_class,
            "role": self.role,
            "input_contract": dict(self.input_contract),
            "expected_output_contract": dict(self.expected_output_contract),
            "budget": self.budget.as_dict(),
            "timeout": self.timeout,
            "validation": list(self.validation),
            "risk": self.risk,
            "benchmark_version": self.benchmark_version,
            "prompt_facts": list(self.prompt_facts),
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.as_dict())


@dataclass(frozen=True)
class ProviderBenchmarkReceipt:
    provider_id: str
    actual_model: str
    task_class: str
    benchmark_id: str
    benchmark_version: str
    prompt_hash: str
    contract_hash: str
    success: bool
    schema_valid: bool
    functional_valid: bool
    interface_valid: bool
    scope_valid: bool
    repair_required: bool
    input_tokens: int | str
    output_tokens: int | str
    total_tokens: int | str
    cost_estimate: float | str
    wall_time_ms: int
    error_class: str
    request_ids: Sequence[str]
    source_commit: str
    gateway_config_hash: str
    structured_output_mode: str = "UNAVAILABLE"
    secret_safe: bool = True

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.actual_model.strip():
            raise ValueError("provider and actual model are required")
        if self.task_class not in TASK_CLASSES or self.error_class not in FAILURE_CLASSES:
            raise ValueError("unsupported benchmark task or failure class")
        if self.wall_time_ms < 0:
            raise ValueError("wall time cannot be negative")
        if self.success and not all((self.schema_valid, self.functional_valid, self.interface_valid, self.scope_valid, self.secret_safe)):
            raise ValueError("successful benchmark receipt must pass every required validation")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ProviderBenchmarkReceipt",
            "schema_version": "1.0",
            "provider_id": self.provider_id,
            "actual_model": self.actual_model,
            "task_class": self.task_class,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "prompt_hash": self.prompt_hash,
            "contract_hash": self.contract_hash,
            "success": self.success,
            "schema_valid": self.schema_valid,
            "functional_valid": self.functional_valid,
            "interface_valid": self.interface_valid,
            "scope_valid": self.scope_valid,
            "repair_required": self.repair_required,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_estimate": self.cost_estimate,
            "wall_time_ms": self.wall_time_ms,
            "error_class": self.error_class,
            "request_ids": list(self.request_ids),
            "source_commit": self.source_commit,
            "gateway_config_hash": self.gateway_config_hash,
            "structured_output_mode": self.structured_output_mode,
            "secret_safe": self.secret_safe,
            "contains_credentials": False,
        }


@dataclass(frozen=True)
class ProviderCapabilityProfile:
    provider_id: str
    actual_model: str
    task_class: str
    samples: int
    functional_success_rate: float
    schema_success_rate: float
    interface_success_rate: float
    scope_success_rate: float
    repair_success_rate: float
    median_tokens: float | str
    median_cost: float | str
    median_latency: float
    failure_classes: Mapping[str, int]
    last_benchmark_version: str
    gateway_config_hash: str
    benchmark_suite_hash: str
    selection_policy_version: str
    eligible: bool
    ineligible_reasons: Sequence[str]
    structured_output_mode: str = "UNAVAILABLE"
    profile_hash: str = ""
    qualification_status: str = "QUALIFIED"
    confidence: str = "MEDIUM"

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "kind": "ProviderCapabilityProfile",
            "schema_version": "1.0",
            "provider_id": self.provider_id,
            "actual_model": self.actual_model,
            "task_class": self.task_class,
            "samples": self.samples,
            "functional_success_rate": self.functional_success_rate,
            "schema_success_rate": self.schema_success_rate,
            "interface_success_rate": self.interface_success_rate,
            "scope_success_rate": self.scope_success_rate,
            "repair_success_rate": self.repair_success_rate,
            "median_tokens": self.median_tokens,
            "median_cost": self.median_cost,
            "median_latency": self.median_latency,
            "failure_classes": dict(self.failure_classes),
            "last_benchmark_version": self.last_benchmark_version,
            "gateway_config_hash": self.gateway_config_hash,
            "benchmark_suite_hash": self.benchmark_suite_hash,
            "selection_policy_version": self.selection_policy_version,
            "eligible": self.eligible,
            "ineligible_reasons": list(self.ineligible_reasons),
            "structured_output_mode": self.structured_output_mode,
            "qualification_status": self.qualification_status,
            "confidence": self.confidence,
            "contains_credentials": False,
        }
        if include_hash:
            value["profile_hash"] = self.profile_hash
        return value

    @property
    def cache_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.provider_id,
            self.actual_model,
            self.gateway_config_hash,
            self.benchmark_suite_hash,
            self.task_class,
            self.selection_policy_version,
        )


@dataclass(frozen=True)
class ProviderSelectionDecision:
    task_class: str
    selected_provider: str
    eligible_providers: Sequence[str]
    profile_refs: Mapping[str, str]
    score: float
    confidence: str
    reason: str
    benchmark_version: str
    selection_policy_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ProviderSelectionDecision",
            "schema_version": "1.0",
            "task_class": self.task_class,
            "selected_provider": self.selected_provider,
            "eligible_providers": list(self.eligible_providers),
            "profile_refs": dict(self.profile_refs),
            "score": self.score,
            "confidence": self.confidence,
            "reason": self.reason,
            "benchmark_version": self.benchmark_version,
            "selection_policy_version": self.selection_policy_version,
        }


@dataclass(frozen=True)
class RunProviderRoutingSnapshot:
    run_id: str
    routes: Mapping[str, str]
    profile_hashes: Mapping[str, str]
    selection_scores: Mapping[str, float]
    benchmark_version: str
    selection_policy_version: str
    fallback: str = "deny"

    def __post_init__(self) -> None:
        if self.fallback != "deny" or not self.routes:
            raise ValueError("run routing must be non-empty and deny fallback")
        object.__setattr__(self, "routes", MappingProxyType(dict(self.routes)))
        object.__setattr__(self, "profile_hashes", MappingProxyType(dict(self.profile_hashes)))
        object.__setattr__(self, "selection_scores", MappingProxyType(dict(self.selection_scores)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "RunProviderRoutingSnapshot",
            "schema_version": "1.0",
            "run_id": self.run_id,
            "routes": dict(self.routes),
            "profile_hashes": dict(self.profile_hashes),
            "selection_scores": dict(self.selection_scores),
            "benchmark_version": self.benchmark_version,
            "selection_policy_version": self.selection_policy_version,
            "fallback": self.fallback,
            "contains_credentials": False,
        }

    def write_once(self, path: pathlib.Path | str) -> pathlib.Path:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(self.as_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target


@dataclass(frozen=True)
class ProjectProviderPlan:
    project_id: str
    simple_domain_provider: str
    persistent_domain_provider: str
    library_provider: str
    repository_patch_provider: str
    repair_provider: str
    capability_build_provider: str
    optional_transport_backup: Mapping[str, str]
    profile_hashes: Mapping[str, str]
    selection_scores: Mapping[str, float]
    confidence: Mapping[str, str]
    plan_hash: str = ""

    def __post_init__(self) -> None:
        value = self.as_dict(include_hash=False)
        expected = canonical_hash(value)
        if self.plan_hash and self.plan_hash != expected:
            raise ValueError("project provider plan hash mismatch")
        object.__setattr__(self, "plan_hash", expected)
        for name in ("optional_transport_backup", "profile_hashes", "selection_scores", "confidence"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"kind": "ProjectProviderPlan", "schema_version": "1.0", "project_id": self.project_id,
                 "simple_domain_provider": self.simple_domain_provider, "persistent_domain_provider": self.persistent_domain_provider,
                 "library_provider": self.library_provider, "repository_patch_provider": self.repository_patch_provider,
                 "repair_provider": self.repair_provider, "capability_build_provider": self.capability_build_provider,
                 "optional_transport_backup": dict(self.optional_transport_backup), "profile_hashes": dict(self.profile_hashes),
                 "selection_scores": dict(self.selection_scores), "confidence": dict(self.confidence), "contains_credentials": False}
        if include_hash:
            value["plan_hash"] = self.plan_hash
        return value

    def authorize_backup(self, task_class: str, *, failure_domain: str, candidate_revision_id: str = "", action: str = "") -> str:
        if candidate_revision_id:
            raise RuntimeError("PROVIDER_ROUTE_AUTHORITY_VIOLATION")
        if failure_domain != "PROVIDER_TRANSPORT_FAILURE" or action != "RETRY_WITH_PRESELECTED_BACKUP":
            raise RuntimeError("PROVIDER_BACKUP_NOT_AUTHORIZED")
        backup = self.optional_transport_backup.get(task_class, "")
        if not backup:
            raise RuntimeError("PROVIDER_BACKUP_NOT_FROZEN")
        return backup
