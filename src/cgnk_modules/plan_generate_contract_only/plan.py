from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import (
    CGNK_PLAN_CONTRACT_ONLY_INSUFFICIENT_CONTEXT,
    CGNK_PLAN_CONTRACT_ONLY_INVALID_GOAL,
    CGNK_PLAN_CONTRACT_ONLY_UNSUPPORTED_REQUEST,
    Diagnostic,
)

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF


def generate_contract_plan(
    goal: Any,
    snapshot: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    goal_text = _goal_text(goal)
    if not goal_text:
        diagnostics.append(Diagnostic(CGNK_PLAN_CONTRACT_ONLY_INVALID_GOAL, "error", "$.goal", "Goal must provide deterministic text", expected="non-empty goal text", actual=goal, involved_ref=MODULE_REF))

    context_paths = sorted(_context_paths(snapshot) | _context_paths(graph))
    if snapshot is None and graph is None:
        diagnostics.append(Diagnostic(CGNK_PLAN_CONTRACT_ONLY_INSUFFICIENT_CONTEXT, "error", "$.context", "Contract-only planning requires snapshot or graph context", expected="ProjectSnapshot or ProjectGraph", actual=None, involved_ref=MODULE_REF))

    proposed_changes = _constraint_changes(constraints)
    blocked_reasons: list[str] = []
    if not proposed_changes and goal_text and context_paths:
        proposed_changes = _rule_based_changes(goal_text, context_paths)
    if not proposed_changes and goal_text and context_paths:
        blocked_reasons.append("unsupported_request")
        diagnostics.append(Diagnostic(CGNK_PLAN_CONTRACT_ONLY_UNSUPPORTED_REQUEST, "warning", "$.goal", "No deterministic rule can safely plan this goal", expected="explicit proposed_changes constraint or supported docs/readme goal", actual=goal_text, involved_ref=MODULE_REF, repair_hints=[{"action": "provide constraints.proposed_changes"}]))

    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    plan = {
        "kind": "ImplementationPlan",
        "version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "goal_summary": goal_text,
        "assumptions": ["contract_only_no_provider", "no_workspace_write", "patch_manifest_required"],
        "proposed_changes": proposed_changes,
        "blocked_reasons": blocked_reasons,
        "required_context": [] if context_paths else ["project_snapshot_or_graph"],
        "risk_summary": _risk_summary(proposed_changes, blocked_reasons, diagnostic_dicts),
        "diagnostics": diagnostic_dicts,
    }
    ok = not any(row["severity"] == "error" for row in diagnostic_dicts) and not blocked_reasons
    return {"ok": ok, "plan": plan, "diagnostics": diagnostic_dicts}


def _goal_text(goal: Any) -> str:
    if isinstance(goal, str):
        return goal.strip()
    if isinstance(goal, dict):
        for key in ("text", "goal", "summary", "description"):
            value = goal.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _context_paths(context: dict[str, Any] | None) -> set[str]:
    if not isinstance(context, dict):
        return set()
    paths: set[str] = set()
    for row in context.get("files", []) or []:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            paths.add(row["path"])
    for row in context.get("nodes", []) or []:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            paths.add(row["path"])
    return paths


def _constraint_changes(constraints: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(constraints, dict):
        return []
    rows = constraints.get("proposed_changes") or constraints.get("allowed_changes") or []
    if not isinstance(rows, list):
        return []
    return [dict(row, index=index) for index, row in enumerate(rows) if isinstance(row, dict)]


def _rule_based_changes(goal_text: str, context_paths: list[str]) -> list[dict[str, Any]]:
    lowered = goal_text.lower()
    changes: list[dict[str, Any]] = []
    if "readme" in lowered and "README.md" in context_paths:
        changes.append({"index": 0, "action": "modify", "path": "README.md", "content_ref": "goal:readme_update", "reason": "Goal explicitly targets README content"})
    elif "doc" in lowered or "documentation" in lowered:
        changes.append({"index": 0, "action": "create", "path": "docs/notes.md", "content_ref": "goal:documentation_note", "reason": "Goal requests documentation and no deterministic existing target was specified"})
    return changes


def _risk_summary(proposed_changes: list[dict[str, Any]], blocked_reasons: list[str], diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    risky = any(row.get("action") in {"delete", "move", "rename"} for row in proposed_changes)
    return {
        "severity": "blocked" if blocked_reasons or any(row["severity"] == "error" for row in diagnostics) else ("review" if risky else "low"),
        "change_count": len(proposed_changes),
        "blocked": bool(blocked_reasons),
        "touches_delete_or_move": risky,
    }
