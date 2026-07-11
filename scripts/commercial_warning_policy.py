#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
from typing import Any

try:
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import base_result


SEVERITIES = ("info", "minor", "major", "critical")
CRITICAL_TOKENS = (
    "missing test report",
    "test_report_missing",
    "screenshot invalid",
    "screenshot_not_passed",
    "final zip missing",
    "missing real final_project_bundle",
    "delivery_manifest missing",
    "missing real delivery_manifest",
    "candidate marker",
    "candidate-as-final",
    "candidate bundle",
    "fake artifact",
    "runnable entry missing",
    "runnable_candidate_missing",
    "manifest points to candidate",
    "corrupt_image",
    "security_blocked",
)
MAJOR_TOKENS = (
    "video blocked",
    "video_missing",
    "product acceptance score below",
    "low_ux_score",
    "major",
    "usable",
)
MINOR_TOKENS = ("ui polish", "optional advanced feature", "readme formatting", "minor")
INFO_TOKENS = ("video duration short", "informational", "info")


def classify_warning(warning: str) -> str:
    text = str(warning or "").replace("_", " ").lower()
    if any(token.replace("_", " ") in text for token in CRITICAL_TOKENS):
        return "critical"
    if any(token.replace("_", " ") in text for token in MAJOR_TOKENS):
        return "major"
    if any(token in text for token in MINOR_TOKENS):
        return "minor"
    if any(token in text for token in INFO_TOKENS):
        return "info"
    return "minor"


def classify_final_warnings(warnings: list[str] | None = None, *, readiness: dict[str, Any] | None = None, final_truth: dict[str, Any] | None = None, integrity: dict[str, Any] | None = None) -> dict[str, Any]:
    collected = [str(item) for item in (warnings or [])]
    for source in (readiness, final_truth, integrity):
        if not isinstance(source, dict):
            continue
        collected.extend(str(item) for item in source.get("warnings", []) if str(item).strip())
        collected.extend(str(item) for item in source.get("blockers", []) if str(item).strip())
    by_severity: dict[str, list[str]] = {key: [] for key in SEVERITIES}
    for item in collected:
        by_severity[classify_warning(item)].append(item)
    has_critical = bool(by_severity["critical"])
    has_major = bool(by_severity["major"])
    pass_final_allowed = not has_critical and not has_major
    recommendation = "FINAL_REJECTED" if has_critical else ("DELIVER_WITH_WARNINGS" if has_major else "PASS_FINAL")
    status = "fail" if has_critical else ("warning" if has_major else "pass")
    return base_result(
        status=status,
        verdict=recommendation,
        warnings=collected,
        blockers=by_severity["critical"],
        metadata={
            "classification": by_severity,
            "pass_final_allowed": pass_final_allowed,
            "final_verdict": recommendation,
        },
    )


def require_warning_classification(final_verdict: str, policy: dict[str, Any] | None) -> dict[str, Any]:
    if str(final_verdict).lower() != "ready_with_warnings":
        return base_result(status="pass", verdict="classification_not_required")
    classified = isinstance(policy, dict) and bool(policy.get("metadata", {}).get("classification"))
    return base_result(status="pass" if classified else "fail", verdict="warning_classified" if classified else "ready_with_warnings_requires_warning_classification")


def write_report(path: pathlib.Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
