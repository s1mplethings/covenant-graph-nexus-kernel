from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from cgkn.artifacts.models import ArtifactRef


SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BlockStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    TIMED_OUT = "TIMED_OUT"
    SKIPPED = "SKIPPED"


class ExecutionErrorCode(str, Enum):
    CONTRACT_ERROR = "CONTRACT_ERROR"
    EXECUTOR_NOT_FOUND = "EXECUTOR_NOT_FOUND"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    INVALID_OUTPUT = "INVALID_OUTPUT"


@dataclass(frozen=True)
class ExecutionError:
    code: ExecutionErrorCode
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "details": dict(self.details)}


@dataclass(frozen=True)
class TaskContext:
    node_goal: str
    node_config: Mapping[str, Any] = field(default_factory=dict)
    dependency_results: Mapping[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[ArtifactRef, ...] = ()
    project_constraints: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.node_goal.strip():
            raise ValueError("task context node_goal is required")
        object.__setattr__(self, "node_config", dict(self.node_config))
        object.__setattr__(self, "dependency_results", dict(self.dependency_results))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "project_constraints", tuple(self.project_constraints))
        object.__setattr__(self, "acceptance", tuple(self.acceptance))

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_goal": self.node_goal,
            "node_config": dict(self.node_config),
            "dependency_results": dict(self.dependency_results),
            "artifact_refs": [item.as_dict() for item in self.artifact_refs],
            "project_constraints": list(self.project_constraints),
            "acceptance": list(self.acceptance),
        }


@dataclass(frozen=True)
class BlockExecutionRequest:
    project_id: str
    run_id: str
    attempt_id: str
    node_id: str
    component_ref: str
    executor_ref: str
    task_context: TaskContext
    input_values: Mapping[str, Any] = field(default_factory=dict)
    input_artifact_refs: tuple[ArtifactRef, ...] = ()
    dependency_result_refs: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    budget: Mapping[str, Any] = field(default_factory=dict)
    declared_effects: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        required = (self.project_id, self.run_id, self.attempt_id, self.node_id, self.component_ref, self.executor_ref)
        if not all(str(item).strip() for item in required):
            raise ValueError("request identity, component_ref, and executor_ref are required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "input_values", dict(self.input_values))
        object.__setattr__(self, "input_artifact_refs", tuple(self.input_artifact_refs))
        object.__setattr__(self, "dependency_result_refs", tuple(self.dependency_result_refs))
        object.__setattr__(self, "budget", dict(self.budget))
        object.__setattr__(self, "declared_effects", tuple(self.declared_effects))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task_context"] = self.task_context.as_dict()
        value["input_artifact_refs"] = [item.as_dict() for item in self.input_artifact_refs]
        return value


@dataclass(frozen=True)
class BlockExecutionResult:
    project_id: str
    run_id: str
    attempt_id: str
    node_id: str
    executor_ref: str
    status: BlockStatus
    outputs: Mapping[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[ArtifactRef, ...] = ()
    test_observations: tuple[Mapping[str, Any], ...] = ()
    error: ExecutionError | None = None
    started_at: str = field(default_factory=utc_now)
    ended_at: str = field(default_factory=utc_now)
    duration_ms: int = 0
    usage: Mapping[str, Any] = field(default_factory=dict)
    retryable: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not all((self.project_id, self.run_id, self.attempt_id, self.node_id, self.executor_ref)):
            raise ValueError("result identity and executor_ref are required")
        if self.status in {BlockStatus.FAILED, BlockStatus.BLOCKED, BlockStatus.TIMED_OUT} and self.error is None:
            raise ValueError("non-success result requires an error")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        object.__setattr__(self, "outputs", dict(self.outputs))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "test_observations", tuple(dict(item) for item in self.test_observations))
        object.__setattr__(self, "usage", dict(self.usage))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def succeeded(self) -> bool:
        return self.status is BlockStatus.SUCCEEDED

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "node_id": self.node_id,
            "executor_ref": self.executor_ref,
            "status": self.status.value,
            "outputs": dict(self.outputs),
            "artifact_refs": [item.as_dict() for item in self.artifact_refs],
            "test_observations": [dict(item) for item in self.test_observations],
            "error": self.error.as_dict() if self.error else None,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "usage": dict(self.usage),
            "retryable": self.retryable,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BlockExecutionResult":
        error = value.get("error")
        return cls(
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            project_id=str(value["project_id"]), run_id=str(value["run_id"]),
            attempt_id=str(value["attempt_id"]), node_id=str(value["node_id"]),
            executor_ref=str(value["executor_ref"]), status=BlockStatus(str(value["status"])),
            outputs=dict(value.get("outputs", {})),
            artifact_refs=tuple(ArtifactRef.from_dict(item) for item in value.get("artifact_refs", [])),
            test_observations=tuple(value.get("test_observations", [])),
            error=ExecutionError(ExecutionErrorCode(error["code"]), str(error["message"]), dict(error.get("details", {}))) if error else None,
            started_at=str(value["started_at"]), ended_at=str(value["ended_at"]),
            duration_ms=int(value.get("duration_ms", 0)), usage=dict(value.get("usage", {})),
            retryable=bool(value.get("retryable", False)), metadata=dict(value.get("metadata", {})),
        )
