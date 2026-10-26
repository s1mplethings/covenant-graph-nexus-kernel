from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from cgkn.providers import GenerationRequest, GenerationResult


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


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class LessonStatus(str, Enum):
    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PROMOTED_TO_POLICY = "PROMOTED_TO_POLICY"
    REVIEW = "REVIEW"
    RETIRED = "RETIRED"


class LessonScopeKind(str, Enum):
    GLOBAL = "GLOBAL"
    TASK_CLASS = "TASK_CLASS"
    OPERATION = "OPERATION"
    CAPABILITY = "CAPABILITY"
    PROVIDER = "PROVIDER"
    PROJECT = "PROJECT"


@dataclass(frozen=True)
class LessonScope:
    task_class: str = ""
    operation: str = ""
    capability_ref: str = ""
    provider_id: str = ""
    project_id: str = ""

    @property
    def kinds(self) -> tuple[LessonScopeKind, ...]:
        rows: list[LessonScopeKind] = []
        if self.task_class:
            rows.append(LessonScopeKind.TASK_CLASS)
        if self.operation:
            rows.append(LessonScopeKind.OPERATION)
        if self.capability_ref:
            rows.append(LessonScopeKind.CAPABILITY)
        if self.provider_id:
            rows.append(LessonScopeKind.PROVIDER)
        if self.project_id:
            rows.append(LessonScopeKind.PROJECT)
        return tuple(rows) or (LessonScopeKind.GLOBAL,)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kinds": [item.value for item in self.kinds],
            "task_class": self.task_class,
            "operation": self.operation,
            "capability_ref": self.capability_ref,
            "provider_id": self.provider_id,
            "project_id": self.project_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LessonScope":
        return cls(*(str(value.get(name, "")) for name in ("task_class", "operation", "capability_ref", "provider_id", "project_id")))


@dataclass(frozen=True)
class LearningEvent:
    event_id: str
    run_id: str
    project_id: str
    task_class: str
    operation: str
    capability_ref: str
    provider_id: str
    candidate_revision_id: str
    failure_domain: str
    failure_code: str
    failure_owner: str
    action_taken: str
    final_outcome: str
    changed_authorities: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    lesson_snapshot_hash: str
    applied_lesson_ids: tuple[str, ...]
    created_at: str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.event_id or not self.run_id or not self.task_class or not self.operation:
            raise ValueError("learning event identity is incomplete")
        object.__setattr__(self, "changed_authorities", tuple(str(item) for item in self.changed_authorities))
        object.__setattr__(self, "evidence_refs", tuple(str(item) for item in self.evidence_refs))
        object.__setattr__(self, "applied_lesson_ids", tuple(str(item) for item in self.applied_lesson_ids))

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "LearningEvent", **{key: _thaw(value) for key, value in self.__dict__.items()}, "contains_credentials": False}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LearningEvent":
        if value.get("kind") != "LearningEvent" or value.get("schema_version") != "1.0":
            raise ValueError("unsupported learning event")
        names = tuple(field.name for field in cls.__dataclass_fields__.values() if field.name != "schema_version")
        data = {name: value.get(name, "") for name in names}
        for name in ("changed_authorities", "evidence_refs", "applied_lesson_ids"):
            data[name] = tuple(value.get(name, ()))
        return cls(**data)


@dataclass(frozen=True)
class LessonRecord:
    lesson_id: str
    revision: int
    status: LessonStatus
    scope: LessonScope
    trigger: str
    guidance: str
    avoid: str
    evidence_refs: tuple[str, ...]
    support_count: int
    contradiction_count: int
    created_at: str
    updated_at: str
    supersedes: str = ""
    retirement_reason: str = ""
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.lesson_id or self.revision < 1 or self.support_count < 0 or self.contradiction_count < 0:
            raise ValueError("lesson identity or counters are invalid")
        if len(self.guidance) + len(self.avoid) > 600:
            raise ValueError("lesson guidance plus avoid exceeds 600 characters")
        if not self.evidence_refs:
            raise ValueError("lesson requires structured evidence refs")
        object.__setattr__(self, "evidence_refs", tuple(str(item) for item in self.evidence_refs))

    @staticmethod
    def stable_id(scope: LessonScope, trigger: str, guidance_category: str, avoid_category: str) -> str:
        digest = canonical_hash({"scope": scope.as_dict(), "trigger": trigger, "guidance_category": guidance_category, "avoid_category": avoid_category})
        return "lesson." + digest.split(":", 1)[1][:24]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "LessonRecord", "schema_version": self.schema_version,
            "lesson_id": self.lesson_id, "revision": self.revision, "status": self.status.value,
            "scope": self.scope.as_dict(), "trigger": self.trigger, "guidance": self.guidance,
            "avoid": self.avoid, "evidence_refs": list(self.evidence_refs),
            "support_count": self.support_count, "contradiction_count": self.contradiction_count,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "supersedes": self.supersedes, "retirement_reason": self.retirement_reason,
            "contains_credentials": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LessonRecord":
        if value.get("kind") != "LessonRecord" or value.get("schema_version") != "1.0":
            raise ValueError("unsupported lesson record")
        return cls(
            str(value["lesson_id"]), int(value["revision"]), LessonStatus(str(value["status"])),
            LessonScope.from_dict(value["scope"]), str(value["trigger"]), str(value["guidance"]),
            str(value["avoid"]), tuple(value.get("evidence_refs", ())), int(value.get("support_count", 0)),
            int(value.get("contradiction_count", 0)), str(value["created_at"]), str(value["updated_at"]),
            str(value.get("supersedes", "")), str(value.get("retirement_reason", "")),
        )


@dataclass(frozen=True)
class LessonQuery:
    task_class: str
    operation: str
    capability_ref: str = ""
    provider_id: str = ""
    project_id: str = ""
    failure_domain: str = ""
    max_lessons: int = 3
    max_chars: int = 1600
    authority_snapshot_hash: str = ""
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.task_class or not self.operation or not 1 <= self.max_lessons <= 3 or not 1 <= self.max_chars <= 1600:
            raise ValueError("lesson query is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {key: _thaw(value) for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class LessonContext:
    lesson_ids: tuple[str, ...]
    lesson_revisions: tuple[int, ...]
    bounded_guidance: tuple[str, ...]
    bounded_avoid: tuple[str, ...]
    lesson_snapshot_hash: str
    context_chars: int
    query_hash: str
    created_at: str
    conflicts: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {key: _thaw(value) for key, value in self.__dict__.items()}


class LessonReader(Protocol):
    def query(self, query: LessonQuery) -> LessonContext: ...


class LessonRecorder(Protocol):
    def record_event(self, event: LearningEvent) -> None: ...
    def finalize_run(self, run_id: str) -> tuple[LessonRecord, ...]: ...


@dataclass(frozen=True)
class GenerationContext:
    authoritative_facts: Mapping[str, Any]
    current_state: Any
    failure_evidence: Any
    lesson_context: LessonContext
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    context_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "authoritative_facts", _freeze(self.authoritative_facts))



