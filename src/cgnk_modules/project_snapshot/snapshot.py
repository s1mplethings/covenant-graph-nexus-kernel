from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_PROJECT_SNAPSHOT_FORBIDDEN_PATH,
    CGNK_PROJECT_SNAPSHOT_ROOT_MISSING,
    CGNK_PROJECT_SNAPSHOT_SCAN_FAILED,
    Diagnostic,
)

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "final_output",
    "project_output",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}
EXCLUDED_SUFFIXES = {".sqlite", ".db", ".zip"}
EXCLUDED_FILE_NAMES = {"ctcp_module_inventory.real.json", "ctcp_transfer_plan.real.json"}


@dataclass(frozen=True)
class ProjectSnapshotResult:
    ok: bool
    snapshot: dict[str, Any] | None
    diagnostics: list[dict[str, Any]]


def collect_project_snapshot(project_root: str | pathlib.Path, include_hashes: bool = True) -> ProjectSnapshotResult:
    root = pathlib.Path(project_root).resolve()
    diagnostics: list[Diagnostic] = []
    if not root.exists() or not root.is_dir():
        diagnostics.append(
            Diagnostic(
                CGNK_PROJECT_SNAPSHOT_ROOT_MISSING,
                "error",
                "$.project_root",
                "Project snapshot root is missing",
                expected="existing directory",
                actual=str(root),
                involved_ref=MODULE_REF,
                source={"root": str(root)},
                repair_hints=[{"action": "pass an existing workspace or project directory"}],
            )
        )
        return ProjectSnapshotResult(False, None, [d.as_dict() for d in diagnostics])

    files: list[dict[str, Any]] = []
    skipped: list[str] = []
    try:
        for path in sorted(root.rglob("*"), key=lambda p: _relative(root, p)):
            rel = _relative(root, path)
            if _is_forbidden(rel, path):
                skipped.append(rel)
                diagnostics.append(
                    Diagnostic(
                        CGNK_PROJECT_SNAPSHOT_FORBIDDEN_PATH,
                        "warning",
                        "$.files",
                        "Excluded generated, archive, database, or cache path from snapshot",
                        expected="allowed project source path",
                        actual=rel,
                        involved_ref=OUTPUT_ARTIFACT_REF,
                        source={"path": rel},
                    )
                )
                continue
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                entry: dict[str, Any] = {
                    "path": rel,
                    "size_bytes": stat.st_size,
                }
                if include_hashes:
                    entry["sha256"] = _sha256(path)
                files.append(entry)
            except OSError as exc:
                diagnostics.append(Diagnostic(CGNK_PROJECT_SNAPSHOT_SCAN_FAILED, "error", f"$.files[{rel}]", "Failed to read file metadata", actual=str(exc), involved_ref=OUTPUT_ARTIFACT_REF, source={"path": rel}))
    except OSError as exc:
        diagnostics.append(Diagnostic(CGNK_PROJECT_SNAPSHOT_SCAN_FAILED, "error", "$.scan", "Failed to scan project root", actual=str(exc), involved_ref=OUTPUT_ARTIFACT_REF, source={"root": str(root)}))

    snapshot = {
        "kind": "ProjectSnapshot",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "metadata": {
            "root": str(root),
            "root_name": root.name,
            "file_count": len(files),
            "total_size_bytes": sum(row["size_bytes"] for row in files),
            "skipped_count": len(skipped),
            "hash_algorithm": "sha256" if include_hashes else None,
        },
        "files": files,
        "skipped_paths": skipped,
    }
    ok = not any(d.severity == "error" for d in diagnostics)
    return ProjectSnapshotResult(ok, snapshot, [d.as_dict() for d in diagnostics])


def _relative(root: pathlib.Path, path: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def _is_forbidden(rel: str, path: pathlib.Path) -> bool:
    parts = set(pathlib.PurePosixPath(rel).parts)
    if parts & EXCLUDED_DIRS:
        return True
    if path.is_file() and path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    return False


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
