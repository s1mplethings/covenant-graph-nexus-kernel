from __future__ import annotations

import hashlib
import json
import pathlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor


EXCLUDED_PARTS = {".git", ".cgkn", "__pycache__", ".pytest_cache", ".coverage", "htmlcov"}


@dataclass(frozen=True)
class ProjectSnapshot:
    files: tuple[dict[str, Any], ...]
    total_bytes: int
    entrypoints: tuple[str, ...]
    test_commands: tuple[str, ...]
    runtime_commands: tuple[str, ...]
    excluded_files: tuple[str, ...]
    generated_at: str
    project_tree_hash: str
    snapshot_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CGKNProjectSnapshot", "schema_version": "1.0", "files": list(self.files),
            "total_file_count": len(self.files), "total_bytes": self.total_bytes,
            "entrypoints": list(self.entrypoints), "test_commands": list(self.test_commands),
            "runtime_commands": list(self.runtime_commands), "excluded_files": list(self.excluded_files),
            "generated_at": self.generated_at, "project_tree_hash": self.project_tree_hash,
            "snapshot_hash": self.snapshot_hash,
        }


def snapshot_project(root: pathlib.Path | str, *, entrypoints: tuple[str, ...] = (), test_commands: tuple[str, ...] = (), runtime_commands: tuple[str, ...] = ()) -> ProjectSnapshot:
    base = pathlib.Path(root).resolve()
    rows: list[dict[str, Any]] = []
    excluded: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if any(part in EXCLUDED_PARTS for part in path.relative_to(base).parts) or relative.startswith("artifacts/"):
            excluded.append(relative)
            continue
        data = path.read_bytes()
        rows.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    tree_payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tree_hash = "sha256:" + hashlib.sha256(tree_payload).hexdigest()
    generated_at = datetime.now(timezone.utc).isoformat()
    body = {
        "files": rows, "total_bytes": sum(row["bytes"] for row in rows), "entrypoints": list(entrypoints),
        "test_commands": list(test_commands), "runtime_commands": list(runtime_commands),
        "excluded_files": excluded, "project_tree_hash": tree_hash,
    }
    snap_hash = "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ProjectSnapshot(tuple(rows), body["total_bytes"], entrypoints, test_commands, runtime_commands, tuple(excluded), generated_at, tree_hash, snap_hash)


class ProjectSnapshotExecutor:
    descriptor = ExecutorDescriptor("project.snapshot@1", "snapshot", ("project.snapshot@1",), ("filesystem.read",))

    def __init__(self, project_root: pathlib.Path | str):
        self.root = pathlib.Path(project_root).resolve()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        try:
            config = request.task_context.node_config
            snapshot = snapshot_project(self.root, entrypoints=tuple(config.get("entrypoints", ())), test_commands=tuple(config.get("test_commands", ())), runtime_commands=tuple(config.get("runtime_commands", ())))
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.SUCCEEDED, outputs=snapshot.as_dict(), started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)))
        except (OSError, ValueError) as exc:
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)), started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)))
