from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any


STATUS_PRIORITY = {
    "PASS": 0,
    "PASS_WITH_LIMITS": 1,
    "NOT_EVALUATED": 2,
    "BLOCKED": 3,
    "BLOCKED_PROVIDER": 3,
    "BLOCKED_LOCAL_MODEL": 3,
    "BLOCKED_ENVIRONMENT": 3,
    "NEEDS_REWORK": 4,
    "FAIL": 5,
}

CANONICAL_STATUSES = set(STATUS_PRIORITY)

REQUIRED_GATES = (
    "requirement",
    "implementation",
    "leaf_behavior_tests",
    "integration_tests",
    "replan",
    "recovery",
    "provider_consumption",
    "collaboration_timing",
    "workspace_identity",
    "test_profiles",
    "clean_start",
    "customer_runtime",
    "ui_public_journey",
    "screenshots",
    "user_review",
    "package",
    "delivery",
    "side_effects",
    "secret_scan",
    "telegram_isolation",
)

OPTIONAL_GATES = (
    "candidate_consistency",
    "evidence_provenance",
    "browser_profile",
    "delivery_profile",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_status(value: Any) -> str:
    raw = str(value or "NOT_EVALUATED").strip().upper()
    return raw if raw in CANONICAL_STATUSES else "NOT_EVALUATED"


def worst_status(statuses: list[Any]) -> str:
    normalized = [normalize_status(status) for status in statuses] or ["NOT_EVALUATED"]
    return max(normalized, key=lambda item: STATUS_PRIORITY[item])


def final_status_from_upstream(statuses: list[Any]) -> str:
    normalized = [normalize_status(status) for status in statuses]
    if "FAIL" in normalized:
        return "FAIL"
    if "NEEDS_REWORK" in normalized or "NOT_EVALUATED" in normalized:
        return "NEEDS_REWORK"
    blocked = [status for status in normalized if status.startswith("BLOCKED")]
    if blocked:
        return blocked[0]
    if "PASS_WITH_LIMITS" in normalized:
        return "PASS_WITH_LIMITS"
    return "PASS" if normalized and all(status == "PASS" for status in normalized) else "NEEDS_REWORK"


ALIASES = {
    "implementation": ("implementation", "tasks"),
    "leaf_behavior_tests": ("leaf_behavior_tests", "tests"),
    "integration_tests": ("integration_tests", "tests"),
    "provider_consumption": ("provider_consumption", "provider"),
    "user_review": ("user_review", "review"),
    "test_profiles": ("test_profiles", "skipped"),
    "customer_runtime": ("customer_runtime", "clean_start"),
    "delivery": ("delivery", "package"),
}


def _input_status(inputs: dict[str, Any], gate: str) -> str:
    matrix = inputs.get("acceptance_matrix") if isinstance(inputs.get("acceptance_matrix"), dict) else {}
    for key in ALIASES.get(gate, (gate,)):
        if key in inputs:
            return normalize_status(inputs.get(key))
        if key in matrix:
            return normalize_status(matrix.get(key))
    return "NOT_EVALUATED"


def canonical_verdict(inputs: dict[str, Any]) -> dict[str, Any]:
    upstream: dict[str, str] = {}
    for key in REQUIRED_GATES:
        upstream[key] = _input_status(inputs, key)
    for key in OPTIONAL_GATES:
        upstream[key] = normalize_status(inputs.get(key, "PASS"))

    package_manifest = inputs.get("package_manifest") if isinstance(inputs.get("package_manifest"), dict) else {}
    if package_manifest.get("status") == "ready_with_warnings" and upstream["package"] == "PASS":
        upstream["package"] = "PASS_WITH_LIMITS"
    if package_manifest.get("status") in {"failed", "rework_blocked"}:
        upstream["package"] = "NEEDS_REWORK"

    if inputs.get("generated_acceptance") == "NOT_EVALUATED":
        upstream["user_review"] = worst_status([upstream["user_review"], "NOT_EVALUATED"])
    if inputs.get("api_only_journey_for_gui") is True:
        upstream["ui_public_journey"] = "NEEDS_REWORK"
    if int(inputs.get("duplicate_screenshot_count") or 0) > 0:
        upstream["screenshots"] = "NEEDS_REWORK"
    if inputs.get("gui_project") is True and inputs.get("screenshots_present") is False:
        upstream["screenshots"] = "NEEDS_REWORK"
    if inputs.get("user_review_required") is True and inputs.get("user_review_completed") is False:
        upstream["user_review"] = "NEEDS_REWORK"
    if inputs.get("package_after_acceptance") is False:
        upstream["package"] = "NEEDS_REWORK"
    if inputs.get("package_contains_nested_zip") is True:
        upstream["package"] = "NEEDS_REWORK"
    if inputs.get("mixed_candidate_evidence") is True:
        upstream["candidate_consistency"] = "NEEDS_REWORK"
    if inputs.get("claimed_evidence_used_for_pass") is True:
        upstream["evidence_provenance"] = "NEEDS_REWORK"
    if inputs.get("quick_full_same_result_file") is True:
        upstream["tests"] = worst_status([upstream["tests"], "PASS_WITH_LIMITS"])
    if inputs.get("unexpected_side_effects"):
        upstream["side_effects"] = "FAIL"
    if inputs.get("secret_leak"):
        upstream["secret_scan"] = "FAIL"

    runner_statuses = {
        key: value
        for key, value in inputs.items()
        if key.endswith("_verdict") or key in {"runner_verdict", "external_verdict", "package_verdict"}
    }
    if "verdict" in inputs and "runner_verdict" not in runner_statuses:
        runner_statuses["runner_verdict"] = inputs.get("verdict")
    overall = final_status_from_upstream(list(upstream.values()))
    return {
        "kind": "CanonicalFinalVerdict",
        "created_at": utc_now(),
        "overall_readiness": overall,
        "upstream_statuses": upstream,
        "status_priority": STATUS_PRIORITY,
        "runner_claims": runner_statuses,
        "conflicts": detect_verdict_conflicts(inputs, overall),
    }


def detect_verdict_conflicts(inputs: dict[str, Any], canonical: str) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    claim_inputs = dict(inputs)
    if "verdict" in claim_inputs and "runner_verdict" not in claim_inputs:
        claim_inputs["runner_verdict"] = claim_inputs.get("verdict")
    for key in ("runner_verdict", "external_verdict", "package_verdict"):
        value = claim_inputs.get(key)
        if value and normalize_status(value) != canonical:
            conflicts.append({"source": key, "claimed": normalize_status(value), "canonical": canonical})
    return conflicts


def write_canonical_verdict(path: str | pathlib.Path, inputs: dict[str, Any]) -> dict[str, Any]:
    verdict = canonical_verdict(inputs)
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return verdict
