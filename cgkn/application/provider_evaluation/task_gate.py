from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contracts import ProjectProviderPlan, ProviderCapabilityProfile, canonical_hash


class TaskClassGateStatus(str, Enum):
    MICRO_ONLY = "MICRO_ONLY"
    PRODUCTION_UNTESTED = "PRODUCTION_UNTESTED"
    PROJECT_QUALIFICATION_IN_PROGRESS = "PROJECT_QUALIFICATION_IN_PROGRESS"
    PRODUCTION_QUALIFIED = "PRODUCTION_QUALIFIED"
    PRODUCTION_QUALIFIED_WITH_REPAIR = "PRODUCTION_QUALIFIED_WITH_REPAIR"
    PRODUCTION_DEGRADED_NO_CANDIDATE = "PRODUCTION_DEGRADED_NO_CANDIDATE"
    PRODUCTION_DEGRADED_CANDIDATE_DEFECT = "PRODUCTION_DEGRADED_CANDIDATE_DEFECT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ProductionQualificationEvidence:
    task_class: str
    provider_id: str
    model: str
    status: TaskClassGateStatus
    evidence_refs: tuple[str, ...] = ()
    candidate_revision_id: str = ""
    project_qualification_id: str = ""


@dataclass(frozen=True)
class TaskClassGateDecision:
    task_class: str
    status: TaskClassGateStatus
    selected_generation_provider: str
    selected_generation_model: str
    selected_backup_provider: str
    selected_repair_provider: str
    profile_hashes: Mapping[str, str]
    production_evidence_refs: tuple[str, ...]
    project_qualification_id: str
    candidate_revision_id: str
    allow_project_run: bool
    reason: str
    decision_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_hashes", MappingProxyType(dict(self.profile_hashes)))
        expected = canonical_hash(self.as_dict(include_hash=False))
        if self.decision_hash and self.decision_hash != expected:
            raise ValueError("task class gate decision hash mismatch")
        object.__setattr__(self, "decision_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "kind": "TaskClassGateDecision", "schema_version": "1.0",
            "task_class": self.task_class, "status": self.status.value,
            "selected_generation_provider": self.selected_generation_provider,
            "selected_generation_model": self.selected_generation_model,
            "selected_backup_provider": self.selected_backup_provider,
            "selected_repair_provider": self.selected_repair_provider,
            "profile_hashes": dict(self.profile_hashes),
            "production_evidence_refs": list(self.production_evidence_refs),
            "project_qualification_id": self.project_qualification_id,
            "candidate_revision_id": self.candidate_revision_id,
            "allow_project_run": self.allow_project_run, "reason": self.reason,
            "contains_credentials": False,
        }
        if include_hash:
            value["decision_hash"] = self.decision_hash
        return value


class TaskClassQualificationGate:
    """Task-local admission over the existing selector/plan authority.

    A degraded task class may run its own project-shaped qualification.  No
    decision observes or aggregates the status of another task class.
    """

    _RUNNABLE = {
        TaskClassGateStatus.PRODUCTION_QUALIFIED,
        TaskClassGateStatus.PRODUCTION_QUALIFIED_WITH_REPAIR,
        TaskClassGateStatus.PROJECT_QUALIFICATION_IN_PROGRESS,
    }

    def __init__(self, profiles: Sequence[ProviderCapabilityProfile], evidence: Sequence[ProductionQualificationEvidence]):
        self._profiles = tuple(profiles)
        self._evidence = {row.task_class: row for row in evidence}

    def decide(self, task_class: str, plan: ProjectProviderPlan, *, project_id: str, model_by_provider: Mapping[str, str]) -> TaskClassGateDecision:
        field = {
            "project.domain.simple": "simple_domain_provider",
            "project.domain.persistent": "persistent_domain_provider",
            "project.domain.library": "library_provider",
            "repository.patch": "repository_patch_provider",
        }.get(task_class)
        if field is None:
            raise ValueError(f"unsupported task class gate: {task_class}")
        selected = str(getattr(plan, field))
        evidence = self._evidence.get(task_class)
        profile_hashes = {p.provider_id: p.profile_hash for p in self._profiles if p.task_class == task_class}
        if evidence and evidence.status in {TaskClassGateStatus.PRODUCTION_QUALIFIED, TaskClassGateStatus.PRODUCTION_QUALIFIED_WITH_REPAIR}:
            status, reason = evidence.status, "task class has production evidence"
        elif evidence and evidence.status in {TaskClassGateStatus.PRODUCTION_DEGRADED_NO_CANDIDATE, TaskClassGateStatus.PRODUCTION_DEGRADED_CANDIDATE_DEFECT}:
            status, reason = TaskClassGateStatus.PROJECT_QUALIFICATION_IN_PROGRESS, "this project is the task-local production qualification"
        else:
            status, reason = TaskClassGateStatus.PROJECT_QUALIFICATION_IN_PROGRESS, "micro-qualified route enters project-shaped qualification"
        backup = str(plan.optional_transport_backup.get(task_class, ""))
        return TaskClassGateDecision(
            task_class, status, selected, str(model_by_provider.get(selected, selected)), backup,
            plan.repair_provider, profile_hashes,
            evidence.evidence_refs if evidence else (),
            evidence.project_qualification_id if evidence else f"qualification.{project_id}",
            evidence.candidate_revision_id if evidence else "",
            status in self._RUNNABLE, reason,
        )


@dataclass
class ProjectActionAuthority:
    """One initial action plus at most one frozen backup or repair action."""

    initial_provider: str
    backup_provider: str = ""
    repair_provider: str = ""
    candidate_revision_id: str = ""
    additional_action: str = ""

    def record_candidate(self, revision_id: str) -> None:
        if not revision_id:
            raise ValueError("candidate revision is required")
        self.candidate_revision_id = revision_id

    def authorize_backup(self, *, failure_domain: str) -> str:
        if self.candidate_revision_id:
            raise RuntimeError("PROVIDER_ROUTE_AUTHORITY_VIOLATION")
        if self.additional_action:
            raise RuntimeError("PROJECT_ADDITIONAL_ACTION_LIMIT")
        if failure_domain != "PROVIDER_TRANSPORT_FAILURE" or not self.backup_provider:
            raise RuntimeError("PROVIDER_BACKUP_NOT_AUTHORIZED")
        self.additional_action = "BACKUP"
        return self.backup_provider

    def authorize_repair(self, *, failure_domain: str) -> str:
        if not self.candidate_revision_id or failure_domain not in {"CANDIDATE_FUNCTIONAL_DEFECT", "BUNDLE_CANDIDATE_DEFECT"}:
            raise RuntimeError("PROVIDER_REPAIR_NOT_AUTHORIZED")
        if self.additional_action:
            raise RuntimeError("PROJECT_ADDITIONAL_ACTION_LIMIT")
        if not self.repair_provider:
            raise RuntimeError("PROVIDER_REPAIR_NOT_FROZEN")
        self.additional_action = "REPAIR"
        return self.repair_provider
