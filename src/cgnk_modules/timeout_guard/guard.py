from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import CGNK_TIMEOUT_GUARD_BUDGET_EXCEEDED, CGNK_TIMEOUT_GUARD_INVALID_TIMINGS, Diagnostic

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF


def evaluate_timeout_budget(timings: Any, budget: dict[str, Any] | int | float | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    total = _total_seconds(timings)
    if total is None:
        diagnostics.append(Diagnostic(CGNK_TIMEOUT_GUARD_INVALID_TIMINGS, "error", "$.timings", "Timings must be a numeric, list, or dictionary of declared durations", expected="declared timing data", actual=type(timings).__name__, involved_ref=MODULE_REF))
        total = 0.0
    limit = _budget_seconds(budget)
    exceeded = total > limit
    if exceeded:
        diagnostics.append(Diagnostic(CGNK_TIMEOUT_GUARD_BUDGET_EXCEEDED, "error", "$.budget.max_total_seconds", "Declared timings exceed budget", expected=f"<= {limit}", actual=total, involved_ref=MODULE_REF))
    budget_summary = {
        "kind": "TimeoutBudgetReport",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "total_seconds": total,
        "max_total_seconds": limit,
        "remaining_seconds": max(0.0, limit - total),
        "exceeded": exceeded,
    }
    ok = not any(d.severity == "error" for d in diagnostics)
    return {"ok": ok, "exceeded": exceeded, "budget_summary": budget_summary, "diagnostics": [d.as_dict() for d in diagnostics]}


def _total_seconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("total_seconds", "elapsed_seconds", "duration_seconds"):
            if isinstance(value.get(key), (int, float)) and not isinstance(value.get(key), bool):
                return float(value[key])
        seconds = [float(v) for v in value.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return sum(seconds) if seconds else None
    if isinstance(value, list):
        totals = [_total_seconds(item) for item in value]
        if any(item is None for item in totals):
            return None
        return sum(item for item in totals if item is not None)
    return None


def _budget_seconds(value: dict[str, Any] | int | float | None) -> float:
    if isinstance(value, bool):
        return 60.0
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if isinstance(value, dict):
        for key in ("max_total_seconds", "total_seconds", "seconds"):
            item = value.get(key)
            if isinstance(item, (int, float)) and not isinstance(item, bool) and item > 0:
                return float(item)
    return 60.0
