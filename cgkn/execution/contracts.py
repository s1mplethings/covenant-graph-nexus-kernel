from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from cgkn.artifacts.models import ArtifactRef


SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


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

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("execution error message is required")
        object.__setattr__(self, "details", _freeze(self.details))

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "details": _thaw(self.details)}


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
        object.__setattr__(self, "node_config", _freeze(self.node_config))
        object.__setattr__(self, "dependency_results", _freeze(self.dependency_results))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "project_constraints", tuple(self.project_constraints))
        object.__setattr__(self, "acceptance", tuple(self.acceptance))

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_goal": self.node_goal,
            "node_config": _thaw(self.node_config),
            "dependency_results": _thaw(self.dependency_results),
            "artifact_refs": [item.as_dict() for item in self.artifact_refs],
            "project_constraints": list(self.project_constraints),
            "acceptance": list(self.acceptance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskContext":
        return cls(
            node_goal=str(value["node_goal"]),
            node_config=dict(value.get("node_config", {})),
            dependency_results=dict(value.get("dependency_results", {})),
            artifact_refs=tuple(ArtifactRef.from_dict(item) for item in value.get("artifact_refs", ())),
            project_constraints=tuple(str(item) for item in value.get("project_constraints", ())),
            acceptance=tuple(str(item) for item in value.get("acceptance", ())),
        )


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
        object.__setattr__(self, "input_values", _freeze(self.input_values))
        object.__setattr__(self, "input_artifact_refs", tuple(self.input_artifact_refs))
        object.__setattr__(self, "dependency_result_refs", tuple(self.dependency_result_refs))
        object.__setattr__(self, "budget", _freeze(self.budget))
        object.__setattr__(self, "declared_effects", tuple(self.declared_effects))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "run_id": self.run_id, "attempt_id": self.attempt_id,
            "node_id": self.node_id, "component_ref": self.component_ref, "executor_ref": self.executor_ref,
            "task_context": self.task_context.as_dict(), "input_values": _thaw(self.input_values),
            "input_artifact_refs": [item.as_dict() for item in self.input_artifact_refs],
            "dependency_result_refs": list(self.dependency_result_refs), "timeout_seconds": self.timeout_seconds,
            "budget": _thaw(self.budget), "declared_effects": list(self.declared_effects),
            "metadata": _thaw(self.metadata), "created_at": self.created_at, "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BlockExecutionRequest":
        return cls(
            project_id=str(value["project_id"]), run_id=str(value["run_id"]), attempt_id=str(value["attempt_id"]),
            node_id=str(value["node_id"]), component_ref=str(value["component_ref"]), executor_ref=str(value["executor_ref"]),
            task_context=TaskContext.from_dict(value["task_context"]), input_values=dict(value.get("input_values", {})),
            input_artifact_refs=tuple(ArtifactRef.from_dict(item) for item in value.get("input_artifact_refs", ())),
            dependency_result_refs=tuple(str(item) for item in value.get("dependency_result_refs", ())),
            timeout_seconds=float(value.get("timeout_seconds", 30.0)), budget=dict(value.get("budget", {})),
            declared_effects=tuple(str(item) for item in value.get("declared_effects", ())), metadata=dict(value.get("metadata", {})),
            created_at=str(value.get("created_at", utc_now())), schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


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
        if self.status in {BlockStatus.SUCCEEDED, BlockStatus.SKIPPED} and self.error is not None:
            raise ValueError("success or skipped result must not contain an error")
        if self.status is BlockStatus.TIMED_OUT and self.error and self.error.code is not ExecutionErrorCode.TIMEOUT:
            raise ValueError("timed out result requires TIMEOUT error")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        object.__setattr__(self, "outputs", _freeze(self.outputs))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "test_observations", tuple(_freeze(item) for item in self.test_observations))
        object.__setattr__(self, "usage", _freeze(self.usage))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

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
            "outputs": _thaw(self.outputs),
            "artifact_refs": [item.as_dict() for item in self.artifact_refs],
            "test_observations": [_thaw(item) for item in self.test_observations],
            "error": self.error.as_dict() if self.error else None,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "usage": _thaw(self.usage),
            "retryable": self.retryable,
            "metadata": _thaw(self.metadata),
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
