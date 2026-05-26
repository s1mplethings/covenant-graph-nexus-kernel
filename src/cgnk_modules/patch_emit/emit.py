from __future__ import annotations

import pathlib
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_PATCH_EMIT_FORBIDDEN_PATH,
    CGNK_PATCH_EMIT_INVALID_CHANGE,
    CGNK_PATCH_EMIT_INVALID_PLAN,
    CGNK_PATCH_EMIT_PATH_ESCAPE,
    Diagnostic,
)

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF

ALLOWED_ACTIONS = {"create", "modify", "delete", "move", "rename"}
FORBIDDEN_DIRS = {".git", "secrets", "final_output", "project_output"}
FORBIDDEN_EXACT = {".env"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".zip"}


def emit_patch_manifest(plan: dict[str, Any], snapshot: dict[str, Any] | None = None, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    changes: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        diagnostics.append(Diagnostic(CGNK_PATCH_EMIT_INVALID_PLAN, "error", "$.plan", "Plan must be a dictionary", expected="dict", actual=type(plan).__name__, involved_ref=MODULE_REF))
    else:
        proposed = plan.get("proposed_changes", plan.get("changes", []))
        if not isinstance(proposed, list):
            diagnostics.append(Diagnostic(CGNK_PATCH_EMIT_INVALID_PLAN, "error", "$.plan.proposed_changes", "Plan proposed_changes must be list-like", expected="list", actual=type(proposed).__name__, involved_ref=MODULE_REF))
        else:
            changes = [_normalize_change(row, index, diagnostics) for index, row in enumerate(proposed)]
    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    valid_changes = [row for row in changes if row.get("action") in ALLOWED_ACTIONS and row.get("path")]
    return {
        "kind": "PatchManifest",
        "version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "changes": changes,
        "file_changes": changes,
        "summary": {
            "change_count": len(changes),
            "valid_change_count": len(valid_changes),
            "blocked": any(row["severity"] == "error" for row in diagnostic_dicts),
        },
        "risk_summary": {
            "severity": "blocked" if any(row["severity"] == "error" for row in diagnostic_dicts) else ("review" if any(row.get("action") in {"delete", "move", "rename"} for row in changes) else "low"),
            "touches_delete_or_move": any(row.get("action") in {"delete", "move", "rename"} for row in changes),
            "diagnostic_count": len(diagnostic_dicts),
        },
        "diagnostics": diagnostic_dicts,
    }


def _normalize_change(row: Any, index: int, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    path = f"$.plan.proposed_changes[{index}]"
    if not isinstance(row, dict):
        diagnostics.append(Diagnostic(CGNK_PATCH_EMIT_INVALID_CHANGE, "error", path, "Plan change must be a dictionary", expected="dict", actual=type(row).__name__, involved_ref=MODULE_REF))
        return {"index": index, "action": None, "path": None, "reason": ""}
    action = row.get("action")
    if action not in ALLOWED_ACTIONS:
        diagnostics.append(Diagnostic(CGNK_PATCH_EMIT_INVALID_CHANGE, "error", f"{path}.action", "Plan change action is not allowed", expected=sorted(ALLOWED_ACTIONS), actual=action, involved_ref=MODULE_REF))
    raw_path = row.get("path") or row.get("target_path")
    normalized = _normalize_path(raw_path, f"{path}.path", diagnostics)
    source_path = _normalize_path(row.get("source_path"), f"{path}.source_path", diagnostics) if row.get("source_path") else None
    target_path = _normalize_path(row.get("target_path"), f"{path}.target_path", diagnostics) if row.get("target_path") else None
    change = {
        "index": index,
        "action": action,
        "path": normalized,
        "source_path": source_path,
        "target_path": target_path,
        "reason": row.get("reason", ""),
        "safety": {
            "apply_patch": False,
            "workspace_write": False,
            "provider_call": False,
        },
    }
    if "content" in row:
        change["content"] = row["content"]
    if "content_ref" in row:
        change["content_ref"] = row["content_ref"]
    return {key: value for key, value in change.items() if value is not None}


def _normalize_path(raw_path: Any, diagnostic_path: str, diagnostics: list[Diagnostic]) -> str | None:
    if not isinstance(raw_path, str) or not raw_path:
        diagnostics.append(Diagnostic(CGNK_PATCH_EMIT_INVALID_CHANGE, "error", diagnostic_path, "Patch path must be a non-empty string", expected="relative path", actual=raw_path, involved_ref=MODULE_REF))
        return None
    path = pathlib.PurePosixPath(raw_path.replace("\\", "/"))
    normalized = path.as_posix()
    if path.is_absolute() or normalized.startswith("/") or any(part == ".." for part in path.parts):
        diagnostics.append(Diagnostic(CGNK_PATCH_EMIT_PATH_ESCAPE, "error", diagnostic_path, "Patch path must not be absolute or escape workspace", expected="relative path without ..", actual=raw_path, involved_ref=MODULE_REF, source={"path": raw_path}))
        return normalized
    if _forbidden_path(normalized):
        diagnostics.append(Diagnostic(CGNK_PATCH_EMIT_FORBIDDEN_PATH, "error", diagnostic_path, "Patch path targets forbidden output, secret, archive, database, or VCS path", expected="allowed project path", actual=normalized, involved_ref=MODULE_REF, source={"path": normalized}))
    return normalized


def _forbidden_path(path: str) -> bool:
    pure = pathlib.PurePosixPath(path)
    return path in FORBIDDEN_EXACT or pure.suffix.lower() in FORBIDDEN_SUFFIXES or bool(set(pure.parts) & FORBIDDEN_DIRS)
