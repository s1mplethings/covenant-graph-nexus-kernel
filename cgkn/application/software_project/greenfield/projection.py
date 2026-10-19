from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contracts import BundleSpec, canonical_hash


PROJECTION_VERSION = "production-domain-projection-v1"


@dataclass(frozen=True)
class ProductionPromptSizePolicy:
    limits: Mapping[str, int]
    version: str = "production-prompt-size-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))

    @classmethod
    def default(cls) -> "ProductionPromptSizePolicy":
        return cls({"project.domain.simple": 18_000, "project.domain.persistent": 26_000,
                    "project.domain.library": 22_000, "repository.patch": 24_000,
                    "project.repair": 20_000})

    def limit_for(self, task_class: str, operation: str) -> int:
        if operation == "REPAIR":
            return self.limits["project.repair"]
        return self.limits[task_class]


@dataclass(frozen=True)
class ProductionPromptProjection:
    task_class: str
    project_id: str
    subject_ref: str
    authoritative_payload: Mapping[str, Any]
    included_authorities: tuple[str, ...]
    excluded_authorities: tuple[str, ...]
    system_chars: int
    user_chars: int
    schema_chars: int
    lesson_chars: int
    total_chars: int
    estimated_input_tokens: int
    projection_version: str
    projection_hash: str
    authority_hashes: Mapping[str, str]
    before_chars: int
    contains_hidden: bool = False
    contains_credentials: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "authoritative_payload", MappingProxyType(dict(self.authoritative_payload)))
        object.__setattr__(self, "authority_hashes", MappingProxyType(dict(self.authority_hashes)))

    @property
    def reduction_ratio(self) -> float:
        return round(1.0 - self.total_chars / self.before_chars, 6) if self.before_chars else 0.0

    def as_dict(self, *, include_payload: bool = True) -> dict[str, Any]:
        value = {
            "kind": "ProductionPromptProjection", "schema_version": "1.0",
            "task_class": self.task_class, "project_id": self.project_id,
            "subject_ref": self.subject_ref,
            "included_authorities": list(self.included_authorities),
            "excluded_authorities": list(self.excluded_authorities),
            "system_chars": self.system_chars, "user_chars": self.user_chars,
            "schema_chars": self.schema_chars, "lesson_chars": self.lesson_chars,
            "total_chars": self.total_chars, "before_chars": self.before_chars,
            "reduction_ratio": self.reduction_ratio,
            "estimated_input_tokens": self.estimated_input_tokens,
            "projection_version": self.projection_version, "projection_hash": self.projection_hash,
            "authority_hashes": dict(self.authority_hashes),
            "contains_hidden": False, "contains_credentials": False,
        }
        if include_payload:
            value["authoritative_payload"] = dict(self.authoritative_payload)
        return value


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def project_domain_prompt(*, task_class: str, project_id: str, package_name: str, domain_goal: str,
                          spec: BundleSpec, obligations: Sequence[Mapping[str, Any]],
                          controlled_errors: Sequence[Mapping[str, Any] | str], system: str,
                          schema: Mapping[str, Any], lessons: Sequence[Mapping[str, Any]] = (),
                          current_sources: Mapping[str, str] | None = None,
                          failure_evidence: Mapping[str, Any] | None = None,
                          operation: str = "GENERATION",
                          size_policy: ProductionPromptSizePolicy | None = None,
                          before_payload: Any = None) -> ProductionPromptProjection:
    policy = size_policy or ProductionPromptSizePolicy.default()
    payload: dict[str, Any] = {
        "subject_ref": spec.bundle_id,
        "project": {"project_id": project_id, "package": package_name, "domain_goal": domain_goal},
        "targets": list(spec.target_paths),
        "domain_interface": spec.interface_contract.as_dict(),
        "domain_obligations": [dict(row) for row in obligations],
        "controlled_errors": [dict(row) if isinstance(row, Mapping) else str(row) for row in controlled_errors],
        "dependency_policy": {"runtime": "PYTHON_STDLIB_ONLY", "network": "FORBIDDEN", "shell": "FORBIDDEN"},
        "lessons": [dict(row) for row in lessons],
    }
    if operation == "REPAIR":
        payload["existing_sources"] = dict(current_sources or {})
        payload["failure_evidence"] = dict(failure_evidence or {})
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    forbidden = ("hidden_acceptance", "hidden_fixture", "cli_plan", "structuredcliplan", "__main__.py", "contract test source", "api_key")
    lowered = serialized.lower()
    if any(marker in lowered for marker in forbidden):
        raise RuntimeError("PRODUCTION_PROMPT_BOUNDARY_VIOLATION")
    system_chars, user_chars, schema_chars = len(system), len(serialized), _json_chars(schema)
    lesson_chars = _json_chars(payload["lessons"])
    total = system_chars + user_chars + schema_chars
    limit = policy.limit_for(task_class, operation)
    if total > limit:
        raise RuntimeError(f"PROMPT_PROJECTION_OVERFLOW:{total}>{limit}")
    authority_hashes = {
        "project": canonical_hash(payload["project"]), "domain_interface": canonical_hash(payload["domain_interface"]),
        "domain_obligations": canonical_hash({"items": payload["domain_obligations"]}),
        "dependency_policy": canonical_hash(payload["dependency_policy"]),
    }
    projection_hash = canonical_hash({"version": PROJECTION_VERSION, "task_class": task_class, "payload": payload,
                                      "system": system, "schema": schema})
    before_chars = _json_chars(before_payload) if before_payload is not None else total
    return ProductionPromptProjection(
        task_class, project_id, spec.bundle_id, payload,
        ("domain_goal", "domain_interface", "domain_obligations", "controlled_errors", "dependency_policy", "target_paths", "relevant_lessons") + (("current_source", "failure_evidence") if operation == "REPAIR" else ()),
        ("cli_contract", "cli_source", "init_source", "contract_tests", "hidden_acceptance", "hidden_fixture", "readme", "package_metadata", "campaign_history", "micro_benchmarks", "unrelated_lessons", "duplicate_project_contract"),
        system_chars, user_chars, schema_chars, lesson_chars, total, (total + 3) // 4,
        PROJECTION_VERSION, projection_hash, authority_hashes, before_chars,
    )


@dataclass(frozen=True)
class ProjectShapedQualificationReceipt:
    qualification_id: str
    task_class: str
    project_id: str
    provider_id: str
    model: str
    project_contract_hash: str
    domain_interface_hash: str
    domain_obligation_hash: str
    prompt_projection_hash: str
    lesson_snapshot_hash: str
    route_snapshot_hash: str
    operation_policy_id: str
    candidate_revision_id: str
    validation_result: str
    qualification_result: str
    reusable_for_project: bool
    receipt_hash: str = ""

    def __post_init__(self) -> None:
        expected = canonical_hash(self.as_dict(include_hash=False))
        if self.receipt_hash and self.receipt_hash != expected:
            raise ValueError("qualification receipt hash mismatch")
        object.__setattr__(self, "receipt_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {key: item for key, item in self.__dict__.items() if key != "receipt_hash"}
        value.update({"kind": "ProjectShapedQualificationReceipt", "schema_version": "1.0", "contains_credentials": False})
        if include_hash:
            value["receipt_hash"] = self.receipt_hash
        return value

    def assert_reusable(self, expected: Mapping[str, str]) -> str:
        fields = ("project_id", "task_class", "project_contract_hash", "domain_interface_hash",
                  "domain_obligation_hash", "prompt_projection_hash", "lesson_snapshot_hash",
                  "route_snapshot_hash", "operation_policy_id", "provider_id", "model")
        if not self.reusable_for_project or any(str(getattr(self, name)) != str(expected.get(name, "")) for name in fields):
            raise RuntimeError("QUALIFICATION_CANDIDATE_REUSE_FAILURE")
        return self.candidate_revision_id
