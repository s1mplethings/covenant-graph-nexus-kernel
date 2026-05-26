from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH,
    CGNK_PATCH_VALIDATE_DUPLICATE_TARGET,
    CGNK_PATCH_VALIDATE_FORBIDDEN_PATH,
    CGNK_PATCH_VALIDATE_INVALID_ACTION,
    CGNK_PATCH_VALIDATE_INVALID_MANIFEST,
    CGNK_PATCH_VALIDATE_MISSING_FIELD,
    CGNK_PATCH_VALIDATE_PATH_ESCAPE,
    Diagnostic,
)

from .contracts import INPUT_ARTIFACT_REF, MODULE_REF, OUTPUT_ARTIFACT_REF

ALLOWED_ACTIONS = {"create", "modify", "delete", "move", "rename"}
CHANGE_KEYS = ("file_changes", "changes", "operations")
FORBIDDEN_DIRS = {".git", "secrets", "final_output", "project_output"}
FORBIDDEN_EXACT = {".env"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".zip"}


@dataclass(frozen=True)
class PatchValidationResult:
    ok: bool
    validation_report: dict[str, Any]
    normalized_manifest: dict[str, Any] | None
    diagnostics: list[dict[str, Any]]


def validate_patch_manifest(
    manifest: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
    project_graph: dict[str, Any] | None = None,
) -> PatchValidationResult:
    diagnostics: list[Diagnostic] = []
    normalized_manifest: dict[str, Any] | None = None
    changes: list[dict[str, Any]] = []

    if not isinstance(manifest, dict):
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_INVALID_MANIFEST, "error", "$.manifest", "Patch manifest must be a dictionary", expected="dict", actual=type(manifest).__name__, involved_ref=INPUT_ARTIFACT_REF))
    else:
        changes_value = _changes_value(manifest)
        if changes_value is None:
            diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_MISSING_FIELD, "error", "$.manifest", "Patch manifest must include file_changes, changes, or operations", expected=list(CHANGE_KEYS), actual=sorted(manifest.keys()), involved_ref=INPUT_ARTIFACT_REF))
        elif not isinstance(changes_value, list):
            diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_INVALID_MANIFEST, "error", "$.manifest.file_changes", "Patch manifest file changes must be list-like", expected="list", actual=type(changes_value).__name__, involved_ref=INPUT_ARTIFACT_REF))
        else:
            changes = [_normalize_change(row, index, diagnostics) for index, row in enumerate(changes_value)]
            normalized_manifest = {
                "kind": manifest.get("kind", "PatchManifest"),
                "artifact_ref": manifest.get("artifact_ref", INPUT_ARTIFACT_REF),
                "file_changes": changes,
            }

    snapshot_paths = _snapshot_paths(snapshot)
    if snapshot is not None and snapshot_paths is None:
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH, "error", "$.snapshot", "Snapshot context is not ProjectSnapshot-like", expected="ProjectSnapshot", actual=snapshot.get("kind") if isinstance(snapshot, dict) else type(snapshot).__name__, involved_ref=MODULE_REF))
    graph_paths = _graph_paths(project_graph)
    if project_graph is not None and graph_paths is None:
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH, "error", "$.project_graph", "Project graph context is not ProjectGraph-like", expected="ProjectGraph", actual=project_graph.get("kind") if isinstance(project_graph, dict) else type(project_graph).__name__, involved_ref=MODULE_REF))

    _check_duplicates(changes, diagnostics)
    if snapshot_paths is not None:
        _check_snapshot_context(changes, snapshot_paths, diagnostics)
    if graph_paths is not None:
        _check_graph_context(changes, graph_paths, diagnostics)

    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    violations = [row for row in diagnostic_dicts if row["severity"] == "error"]
    warnings = [row for row in diagnostic_dicts if row["severity"] == "warning"]
    ok = not violations
    report = {
        "kind": "ValidationReport",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "ok": ok,
        "checked_at": "deterministic",
        "manifest_summary": {
            "change_count": len(changes),
            "actions": _action_counts(changes),
            "targets": sorted({target for change in changes for target in _targets_for(change)}),
        },
        "violations": violations,
        "warnings": warnings,
        "diagnostics": diagnostic_dicts,
        "risk_summary": _risk_summary(changes, violations, warnings),
    }
    return PatchValidationResult(ok, report, normalized_manifest, diagnostic_dicts)


def _changes_value(manifest: dict[str, Any]) -> Any:
    for key in CHANGE_KEYS:
        if key in manifest:
            return manifest[key]
    return None


def _normalize_change(row: Any, index: int, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    path = f"$.manifest.file_changes[{index}]"
    if not isinstance(row, dict):
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_INVALID_MANIFEST, "error", path, "File change must be a dictionary", expected="dict", actual=type(row).__name__, involved_ref=INPUT_ARTIFACT_REF))
        return {"index": index, "action": None, "path": None}
    action = row.get("action")
    raw_path = row.get("path")
    if action is None:
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_MISSING_FIELD, "error", f"{path}.action", "File change is missing action", expected=sorted(ALLOWED_ACTIONS), actual=None, involved_ref=INPUT_ARTIFACT_REF))
    elif action not in ALLOWED_ACTIONS:
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_INVALID_ACTION, "error", f"{path}.action", "File change action is not allowed", expected=sorted(ALLOWED_ACTIONS), actual=action, involved_ref=INPUT_ARTIFACT_REF))
    if raw_path is None:
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_MISSING_FIELD, "error", f"{path}.path", "File change is missing path", expected="relative normalized path", actual=None, involved_ref=INPUT_ARTIFACT_REF))
    normalized_path = _normalize_path(raw_path, f"{path}.path", diagnostics) if raw_path is not None else None
    to_path = row.get("to_path") or row.get("new_path")
    normalized_to = _normalize_path(to_path, f"{path}.to_path", diagnostics) if to_path is not None else None
    if action in {"move", "rename"} and normalized_to is None:
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_MISSING_FIELD, "error", f"{path}.to_path", "Move/rename change requires to_path or new_path", expected="relative normalized destination path", actual=None, involved_ref=INPUT_ARTIFACT_REF))
    return {
        "index": index,
        "action": action,
        "path": normalized_path,
        "to_path": normalized_to,
    }


def _normalize_path(raw_path: Any, diagnostic_path: str, diagnostics: list[Diagnostic]) -> str | None:
    if not isinstance(raw_path, str) or raw_path == "":
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_INVALID_MANIFEST, "error", diagnostic_path, "Patch path must be a non-empty string", expected="relative path string", actual=raw_path, involved_ref=INPUT_ARTIFACT_REF))
        return None
    path = pathlib.PurePosixPath(raw_path.replace("\\", "/"))
    normalized = path.as_posix()
    if path.is_absolute() or normalized.startswith("/") or any(part == ".." for part in path.parts):
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_PATH_ESCAPE, "error", diagnostic_path, "Patch path must not be absolute or escape workspace", expected="relative path without ..", actual=raw_path, involved_ref=INPUT_ARTIFACT_REF, source={"path": raw_path}))
        return normalized
    if normalized != raw_path.replace("\\", "/") or "." in path.parts:
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_INVALID_MANIFEST, "warning", diagnostic_path, "Patch path should be normalized", expected=normalized, actual=raw_path, involved_ref=INPUT_ARTIFACT_REF))
    if _forbidden_path(normalized):
        diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_FORBIDDEN_PATH, "error", diagnostic_path, "Patch path targets forbidden output, secret, archive, database, or VCS path", expected="allowed project path", actual=normalized, involved_ref=INPUT_ARTIFACT_REF, source={"path": normalized}))
    return normalized


def _forbidden_path(path: str) -> bool:
    pure = pathlib.PurePosixPath(path)
    if path in FORBIDDEN_EXACT:
        return True
    if pure.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    parts = set(pure.parts)
    return bool(parts & FORBIDDEN_DIRS)


def _check_duplicates(changes: list[dict[str, Any]], diagnostics: list[Diagnostic]) -> None:
    seen: dict[str, int] = {}
    for change in changes:
        for target in _targets_for(change):
            if target in seen:
                diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_DUPLICATE_TARGET, "error", f"$.manifest.file_changes[{change['index']}]", "Patch manifest targets the same path more than once", expected="unique target paths", actual=target, involved_ref=INPUT_ARTIFACT_REF, source={"first_index": seen[target], "duplicate_index": change["index"]}))
            else:
                seen[target] = change["index"]


def _check_snapshot_context(changes: list[dict[str, Any]], snapshot_paths: set[str], diagnostics: list[Diagnostic]) -> None:
    for change in changes:
        action = change.get("action")
        path = change.get("path")
        to_path = change.get("to_path")
        if not path:
            continue
        if action in {"delete", "modify", "move", "rename"} and path not in snapshot_paths:
            diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH, "error", f"$.manifest.file_changes[{change['index']}].path", f"{action} action requires existing source path in snapshot context", expected="path exists in snapshot", actual=path, involved_ref=INPUT_ARTIFACT_REF))
        if action == "create" and path in snapshot_paths:
            diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH, "warning", f"$.manifest.file_changes[{change['index']}].path", "Create action targets an existing path in snapshot context", expected="new path", actual=path, involved_ref=INPUT_ARTIFACT_REF))
        if action in {"move", "rename"} and to_path and to_path in snapshot_paths:
            diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH, "warning", f"$.manifest.file_changes[{change['index']}].to_path", "Move/rename destination already exists in snapshot context", expected="new destination path", actual=to_path, involved_ref=INPUT_ARTIFACT_REF))


def _check_graph_context(changes: list[dict[str, Any]], graph_paths: set[str], diagnostics: list[Diagnostic]) -> None:
    for change in changes:
        path = change.get("path")
        action = change.get("action")
        if action in {"delete", "modify", "move", "rename"} and path and path not in graph_paths:
            diagnostics.append(Diagnostic(CGNK_PATCH_VALIDATE_CONTEXT_MISMATCH, "warning", f"$.project_graph.nodes[{change['index']}]", "Project graph context does not include source path", expected="path represented in graph", actual=path, involved_ref=INPUT_ARTIFACT_REF))


def _snapshot_paths(snapshot: dict[str, Any] | None) -> set[str] | None:
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict) or snapshot.get("kind") != "ProjectSnapshot" or not isinstance(snapshot.get("files"), list):
        return None
    return {row.get("path") for row in snapshot["files"] if isinstance(row, dict) and isinstance(row.get("path"), str)}


def _graph_paths(graph: dict[str, Any] | None) -> set[str] | None:
    if graph is None:
        return None
    if not isinstance(graph, dict) or graph.get("kind") != "ProjectGraph" or not isinstance(graph.get("nodes"), list):
        return None
    return {row.get("path") for row in graph["nodes"] if isinstance(row, dict) and row.get("kind") == "file" and isinstance(row.get("path"), str)}


def _targets_for(change: dict[str, Any]) -> list[str]:
    targets = []
    if change.get("path"):
        targets.append(change["path"])
    if change.get("to_path"):
        targets.append(change["to_path"])
    return targets


def _action_counts(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {action: 0 for action in sorted(ALLOWED_ACTIONS)}
    for change in changes:
        action = change.get("action")
        if action in counts:
            counts[action] += 1
    return {key: value for key, value in counts.items() if value}


def _risk_summary(changes: list[dict[str, Any]], violations: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    action_risk = {
        "create": 1,
        "modify": 2,
        "delete": 3,
        "move": 3,
        "rename": 3,
    }
    max_action_risk = max([action_risk.get(change.get("action"), 0) for change in changes] or [0])
    severity = "blocked" if violations else ("review" if warnings or max_action_risk >= 3 else "low")
    return {
        "severity": severity,
        "max_action_risk": max_action_risk,
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "touches_delete_or_move": any(change.get("action") in {"delete", "move", "rename"} for change in changes),
    }
