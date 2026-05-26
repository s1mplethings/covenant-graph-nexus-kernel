from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import CGNK_TRACE_SUMMARY_INVALID_INPUT, Diagnostic

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF


def summarize_trace_events(events: Any) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    rows = _event_rows(events)
    if rows is None:
        diagnostics.append(Diagnostic(CGNK_TRACE_SUMMARY_INVALID_INPUT, "error", "$.events", "Trace events input must be a list or a dict containing events", expected="event list", actual=type(events).__name__, involved_ref=MODULE_REF))
        rows = []

    by_type = _counts(_event_type(row) for row in rows)
    providers = sorted({str(row.get("provider")) for row in rows if row.get("provider")})
    artifacts = sorted({str(row.get("artifact") or row.get("artifact_ref")) for row in rows if row.get("artifact") or row.get("artifact_ref")})
    diagnostic_rows = _diagnostics(rows)
    summary = {
        "kind": "TraceSummary",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "event_count": len(rows),
        "by_type": by_type,
        "providers": providers,
        "artifacts": artifacts,
        "diagnostics_count": len(diagnostic_rows),
        "diagnostics_codes": sorted({str(row.get("code")) for row in diagnostic_rows if row.get("code")}),
        "metadata_keys": sorted({str(key) for row in rows for key in row if key not in {"type", "event", "provider", "artifact", "artifact_ref", "diagnostics"}}),
    }
    local_diagnostics = [d.as_dict() for d in diagnostics]
    return {"ok": not local_diagnostics, "summary": summary, "diagnostics": local_diagnostics, **{key: summary[key] for key in ("event_count", "by_type", "providers", "artifacts", "diagnostics_count", "diagnostics_codes")}}


def _event_rows(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, dict):
        value = value.get("events")
    if not isinstance(value, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append(dict(sorted(item.items())))
        else:
            rows.append({"type": "unknown", "value": str(item)})
    return rows


def _event_type(row: dict[str, Any]) -> str:
    value = row.get("type") or row.get("event") or "unknown"
    return str(value)


def _diagnostics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        value = row.get("diagnostics")
        if isinstance(value, list):
            out.extend(item for item in value if isinstance(item, dict))
    return out


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}
