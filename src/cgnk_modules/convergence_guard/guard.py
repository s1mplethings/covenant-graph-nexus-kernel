from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import (
    CGNK_CONVERGENCE_GUARD_INVALID_HISTORY,
    CGNK_CONVERGENCE_GUARD_MAX_PASSES,
    CGNK_CONVERGENCE_GUARD_STALLED,
    Diagnostic,
)

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF


def evaluate_convergence(history: Any, thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    if not isinstance(history, list):
        diagnostics.append(Diagnostic(CGNK_CONVERGENCE_GUARD_INVALID_HISTORY, "error", "$.history", "Convergence history must be a list", expected="list", actual=type(history).__name__, involved_ref=MODULE_REF))
        history = []
    thresholds = thresholds if isinstance(thresholds, dict) else {}
    max_passes = _int(thresholds.get("max_passes"), 5)
    repeat_limit = _int(thresholds.get("repeat_hash_limit"), 2)
    pass_count = sum(1 for row in history if _passed(row))
    hashes = [_hash_for(row) for row in history]
    repeated_hashes = {key: hashes.count(key) for key in sorted(set(hashes)) if key and hashes.count(key) >= repeat_limit}
    converged = pass_count > 0
    stalled = bool(repeated_hashes) and not converged
    reason = "converged" if converged else "insufficient_history"
    if stalled:
        reason = "repeated_hash"
        diagnostics.append(Diagnostic(CGNK_CONVERGENCE_GUARD_STALLED, "warning", "$.history", "History appears stalled on repeated result hashes", expected="changing or passing results", actual=repeated_hashes, involved_ref=MODULE_REF))
    if len(history) >= max_passes and not converged:
        reason = "max_passes"
        stalled = True
        diagnostics.append(Diagnostic(CGNK_CONVERGENCE_GUARD_MAX_PASSES, "error", "$.thresholds.max_passes", "History reached maximum declared passes without convergence", expected=f"< {max_passes}", actual=len(history), involved_ref=MODULE_REF))
    report = {
        "kind": "ConvergenceReport",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "converged": converged,
        "stalled": stalled,
        "reason": reason,
        "repeated_hashes": repeated_hashes,
        "pass_count": pass_count,
    }
    ok = not any(d.severity == "error" for d in diagnostics)
    return {"ok": ok, "report": report, "converged": converged, "stalled": stalled, "reason": reason, "repeated_hashes": repeated_hashes, "pass_count": pass_count, "diagnostics": [d.as_dict() for d in diagnostics]}


def _passed(row: Any) -> bool:
    if isinstance(row, dict):
        return row.get("ok") is True or str(row.get("status", "")).lower() in {"pass", "passed", "success", "converged"}
    return str(row).lower() in {"pass", "passed", "success", "converged"}


def _hash_for(row: Any) -> str | None:
    if isinstance(row, dict):
        for key in ("hash", "graph_hash", "output_hash", "result_hash"):
            value = row.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default
