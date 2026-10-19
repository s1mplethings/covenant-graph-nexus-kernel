from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ProjectResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    NEEDS_REWORK = "NEEDS_REWORK"


class FailureClass(str, Enum):
    PROJECT_FAILURE = "PROJECT_FAILURE"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    HARNESS_FAILURE = "HARNESS_FAILURE"
    TIMEOUT = "TIMEOUT"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    CONTRACT_FAILURE = "CONTRACT_FAILURE"


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class WorkerScope:
    allowed_paths: tuple[str, ...]
    target_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = (
        ".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"
    )
    max_actions: int = 4
    max_write_files: int = 2
    max_total_output_bytes: int = 64_000
    allow_create: bool = True
    allow_patch: bool = True
    allow_delete: bool = False

    def __post_init__(self) -> None:
        if not self.allowed_paths:
            raise ValueError("worker scope requires explicit allowed paths")
        for raw in (*self.allowed_paths, *self.target_paths):
            path = pathlib.PurePosixPath(str(raw).replace("\\", "/"))
            if path.is_absolute() or not str(path) or ".." in path.parts:
                raise ValueError("worker scope paths must be safe and relative")
        targets = self.target_paths or self.allowed_paths
        if not targets or len(targets) > min(3, self.max_write_files) or any(item not in self.allowed_paths for item in targets):
            raise ValueError("worker target_paths must fit the cohesive path and write-file limits")
        object.__setattr__(self, "target_paths", tuple(targets))
        if self.max_actions < 1 or self.max_write_files < 1 or self.max_total_output_bytes < 1:
            raise ValueError("worker scope limits must be positive")
        if self.allow_delete:
            raise ValueError("project workers may not delete files")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkerScope":
        return cls(
            allowed_paths=tuple(str(item) for item in value.get("allowed_paths", ())),
            target_paths=tuple(str(item) for item in value.get("target_paths", ())),
            protected_paths=tuple(str(item) for item in value.get("protected_paths", cls.__dataclass_fields__["protected_paths"].default)),
            max_actions=int(value.get("max_actions", 4)),
            max_write_files=int(value.get("max_write_files", 2)),
            max_total_output_bytes=int(value.get("max_total_output_bytes", 64_000)),
            allow_create=bool(value.get("allow_create", True)),
            allow_patch=bool(value.get("allow_patch", True)),
            allow_delete=bool(value.get("allow_delete", False)),
        )


@dataclass(frozen=True)
class AcceptanceResult:
    status: ProjectResultStatus
    failure_class: FailureClass | None
    sanitized_summary: str
    failed_requirement_ids: tuple[str, ...] = ()
    return_codes: tuple[int, ...] = ()
    stdout_tail: str = ""
    stderr_tail: str = ""
    runtime_observations: Mapping[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    snapshot_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        value = {
            "kind": "CGKNExternalAcceptanceReceipt",
            "schema_version": "1.0",
            "status": self.status.value,
            "failure_class": self.failure_class.value if self.failure_class else None,
            "sanitized_summary": self.sanitized_summary,
            "failed_requirement_ids": list(self.failed_requirement_ids),
            "return_codes": list(self.return_codes),
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "runtime_observations": dict(self.runtime_observations),
            "duration_ms": self.duration_ms,
            "snapshot_hash": self.snapshot_hash,
        }
        return value | {"receipt_hash": canonical_hash(value)}
