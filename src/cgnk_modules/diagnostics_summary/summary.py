from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import CGNK_DIAGNOSTICS_SUMMARY_INVALID_INPUT, Diagnostic

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF


def summarize_diagnostics(diagnostics: Any) -> dict[str, Any]:
    local: list[Diagnostic] = []
    rows = _diagnostic_rows(diagnostics)
    if rows is None:
        local.append(Diagnostic(CGNK_DIAGNOSTICS_SUMMARY_INVALID_INPUT, "error", "$.diagnostics", "Diagnostics input must be a list or a dict containing diagnostics", expected="diagnostic list", actual=type(diagnostics).__name__, involved_ref=MODULE_REF))
        rows = []
    by_severity = _counts(row.get("severity", "unknown") for row in rows)
    by_code = _counts(row.get("code", "UNKNOWN") for row in rows)
    involved_refs = sorted({row["involved_ref"] for row in rows if isinstance(row.get("involved_ref"), str)})
    repairable = sum(1 for row in rows if row.get("repair_hints"))
    summary = {
        "kind": "DiagnosticsSummary",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "total": len(rows),
        "by_severity": by_severity,
        "by_code": by_code,
        "involved_refs": involved_refs,
        "repairability_summary": {
            "repairable_count": repairable,
            "blocked_count": sum(1 for row in rows if row.get("severity") == "error" and not row.get("repair_hints")),
            "warning_count": by_severity.get("warning", 0),
        },
    }
    return {"ok": not any(d.severity == "error" for d in local), "summary": summary, "diagnostics": [d.as_dict() for d in local], **{k: summary[k] for k in ("total", "by_severity", "by_code", "involved_refs", "repairability_summary")}}


def _diagnostic_rows(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, dict):
        value = value.get("diagnostics")
    if not isinstance(value, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append(dict(sorted(item.items())))
        else:
            rows.append({"code": "UNKNOWN", "severity": "warning", "message": str(item)})
    return rows


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}
