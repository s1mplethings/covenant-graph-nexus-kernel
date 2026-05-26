from __future__ import annotations

import json
from typing import Any

from cgnk_core.diagnostics import CGNK_BENCHMARK_SUMMARY_INVALID_INPUT, Diagnostic

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF


def summarize_benchmark_report(report_or_summary: Any) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    report = _coerce_report(report_or_summary, diagnostics)
    metrics = _metrics(report) if isinstance(report, dict) else {}
    warnings = _warnings(report) if isinstance(report, dict) else []
    status = _status(report) if isinstance(report, dict) else "invalid"
    summary = {
        "kind": "BenchmarkReport",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "status": status,
        "summary": {
            "metric_count": len(metrics),
            "warning_count": len(warnings),
            "source_kind": report.get("kind") if isinstance(report, dict) else None,
        },
        "metrics": metrics,
        "warnings": warnings,
    }
    ok = not diagnostics and status not in {"failed", "error", "invalid"}
    return {"ok": ok, "summary": summary, "metrics": metrics, "warnings": warnings, "diagnostics": [d.as_dict() for d in diagnostics]}


def _coerce_report(value: Any, diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            diagnostics.append(Diagnostic(CGNK_BENCHMARK_SUMMARY_INVALID_INPUT, "error", "$.report", "Benchmark report string must be JSON object text", expected="JSON object", actual="non-json string", involved_ref=MODULE_REF))
            return None
        if isinstance(parsed, dict):
            return parsed
    diagnostics.append(Diagnostic(CGNK_BENCHMARK_SUMMARY_INVALID_INPUT, "error", "$.report", "Benchmark summary input must be an existing report dictionary", expected="dict", actual=type(value).__name__, involved_ref=MODULE_REF))
    return None


def _metrics(report: dict[str, Any]) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {}
    for key, value in sorted(report.items()):
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            metrics[key] = value
    nested = report.get("metrics")
    if isinstance(nested, dict):
        for key, value in sorted(nested.items()):
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                metrics[f"metrics.{key}"] = value
    return metrics


def _warnings(report: dict[str, Any]) -> list[str]:
    value = report.get("warnings", [])
    if isinstance(value, list):
        return sorted(str(item) for item in value)
    return [str(value)] if value else []


def _status(report: dict[str, Any]) -> str:
    for key in ("status", "result", "outcome"):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            return value.lower()
    if report.get("ok") is False:
        return "failed"
    if report.get("ok") is True:
        return "ok"
    return "unknown"
