from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any


READY_DECISIONS = {"NOT_READY", "REVIEW_REQUIRED", "COMMERCIAL_CANDIDATE", "COMMERCIAL_READY"}
HUMAN_REVIEW_FIELDS = {
    "reviewer",
    "reviewed_at",
    "sample_count_reviewed",
    "approved",
    "notes",
    "blocking_findings",
    "review_scope",
}
HUMAN_REVIEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "CGKN Human Review Evidence",
    "type": "object",
    "required": sorted(HUMAN_REVIEW_FIELDS),
    "properties": {
        "reviewer": {"type": "string", "minLength": 1},
        "reviewed_at": {"type": "string", "minLength": 1},
        "sample_count_reviewed": {"type": "integer", "minimum": 0},
        "approved": {"type": "boolean"},
        "notes": {"type": "string"},
        "blocking_findings": {"type": "array", "items": {"type": "string"}},
        "review_scope": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "min_samples": 3,
    "min_reference_coverage": 1.0,
    "max_token_error_rate": 0.25,
    "max_character_error_rate": 0.20,
    "max_failed_samples": 0,
    "max_timeout_samples": 0,
    "max_invalid_output_samples": 0,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_human_review_schema(path: pathlib.Path) -> pathlib.Path:
    write_json(pathlib.Path(path), HUMAN_REVIEW_SCHEMA)
    return pathlib.Path(path)


def load_json(path: pathlib.Path | None) -> dict[str, Any]:
    if not path or not pathlib.Path(path).exists():
        return {}
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def validate_human_review(review: dict[str, Any], *, min_samples: int) -> tuple[str, list[str]]:
    if not review:
        return "missing", ["human_review_evidence_missing"]
    blockers: list[str] = []
    for field in sorted(HUMAN_REVIEW_FIELDS - set(review)):
        blockers.append(f"human_review_{field}_missing")
    findings = review.get("blocking_findings", [])
    scope = review.get("review_scope", [])
    if review.get("approved") is not True:
        blockers.append("human_review_not_approved")
    if not isinstance(findings, list) or findings:
        blockers.append("human_review_has_blocking_findings")
    if not isinstance(scope, list) or not scope:
        blockers.append("human_review_scope_missing")
    if int(review.get("sample_count_reviewed", 0) or 0) < min_samples:
        blockers.append("human_review_sample_count_below_minimum")
    return ("approved" if not blockers else "rejected"), blockers


def evaluate(
    *,
    project_dir: pathlib.Path,
    capability_manifest: dict[str, Any],
    promotion_report: dict[str, Any],
    reliability_report: dict[str, Any],
    human_review_evidence: dict[str, Any] | None,
    artifact_integrity_status: str,
    delivery_status: str,
    output_path: pathlib.Path | None = None,
    thresholds: dict[str, Any] | None = None,
    enabled: bool = True,
    gate_test_only: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    limits = dict(DEFAULT_THRESHOLDS)
    limits.update(thresholds or {})
    capabilities = capability_manifest.get("capabilities", {}) if isinstance(capability_manifest.get("capabilities"), dict) else {}
    asr = capabilities.get("asr", {}) if isinstance(capabilities.get("asr"), dict) else {}
    quality = capabilities.get("asr_quality", {}) if isinstance(capabilities.get("asr_quality"), dict) else {}
    decode = capabilities.get("media_decode", {}) if isinstance(capabilities.get("media_decode"), dict) else {}
    user_media = capabilities.get("user_media_input", {}) if isinstance(capabilities.get("user_media_input"), dict) else {}
    promotion_decision = str(promotion_report.get("promotion_decision") or "COMMERCIAL_BETA")
    adapter_kind = str(promotion_report.get("adapter_kind") or quality.get("adapter_kind") or asr.get("adapter_kind") or "none")
    evidence_tier = str(promotion_report.get("evidence_tier") or quality.get("evidence_tier") or asr.get("evidence_tier") or "none")
    metrics = promotion_report.get("quality_metrics", {}) if isinstance(promotion_report.get("quality_metrics"), dict) else {}
    review_status, review_blockers = validate_human_review(human_review_evidence or {}, min_samples=int(limits["min_samples"]))
    blockers: list[str] = []
    if not enabled:
        blockers.append("commercial_ready_gate_not_requested")
    if adapter_kind != "real_local_asr":
        blockers.append("ready_adapter_kind_not_real_local_asr")
    if evidence_tier not in {"production_candidate", "production_verified"}:
        blockers.append(f"ready_evidence_tier_insufficient:{evidence_tier}")
    if promotion_decision != "COMMERCIAL_CANDIDATE":
        blockers.append(f"promotion_decision_not_candidate:{promotion_decision}")
    if promotion_report.get("promotion_blockers"):
        blockers.append("promotion_report_has_blockers")
    if asr.get("production_asr") is not True:
        blockers.append("production_asr_not_verified_true")
    if asr.get("degraded") is not False:
        blockers.append("ready_asr_path_degraded")
    if str(quality.get("asr_quality_status") or "") not in {"production_candidate", "production_verified"}:
        blockers.append("asr_multi_sample_quality_not_pass")
    if int(quality.get("sample_count", 0) or 0) < int(limits["min_samples"]):
        blockers.append("ready_sample_count_below_minimum")
    if int(quality.get("failed_samples", 0) or 0) > int(limits["max_failed_samples"]):
        blockers.append("ready_failed_samples_above_threshold")
    if int(quality.get("timeout_samples", 0) or 0) > int(limits["max_timeout_samples"]):
        blockers.append("ready_timeout_samples_above_threshold")
    if int(quality.get("invalid_output_samples", 0) or 0) > int(limits["max_invalid_output_samples"]):
        blockers.append("ready_invalid_output_samples_above_threshold")
    coverage = float(promotion_report.get("reference_transcript_coverage", 0.0) or 0.0)
    if coverage < float(limits["min_reference_coverage"]):
        blockers.append("ready_reference_transcript_coverage_below_threshold")
    token_error_rate = metrics.get("token_error_rate")
    char_error_rate = metrics.get("character_error_rate")
    if token_error_rate is None or float(token_error_rate) > float(limits["max_token_error_rate"]):
        blockers.append("ready_token_error_rate_unavailable_or_high")
    if char_error_rate is None or float(char_error_rate) > float(limits["max_character_error_rate"]):
        blockers.append("ready_character_error_rate_unavailable_or_high")
    if str(reliability_report.get("reliability_status") or "not_ready") != "pass":
        blockers.append("repeat_reliability_not_pass")
    blockers.extend(str(item) for item in reliability_report.get("blockers", []) or [])
    if str(decode.get("status") or "not_attempted") != "verified":
        blockers.append("ready_production_decode_missing")
    if str(user_media.get("status") or "not_configured") != "verified":
        blockers.append("ready_user_media_input_missing")
    if str(artifact_integrity_status).upper() != "PASS":
        blockers.append("ready_artifact_integrity_not_pass")
    if str(delivery_status).upper() != "PASS":
        blockers.append("ready_delivery_evidence_not_pass")
    blockers.extend(review_blockers)
    blockers = list(dict.fromkeys(blockers))
    non_review_blockers = [item for item in blockers if not item.startswith("human_review_")]
    if not blockers:
        decision = "COMMERCIAL_READY"
    elif not non_review_blockers and review_blockers:
        decision = "REVIEW_REQUIRED"
    elif promotion_decision == "COMMERCIAL_CANDIDATE":
        decision = "COMMERCIAL_CANDIDATE"
    else:
        decision = "NOT_READY"
    commercial_ready = decision == "COMMERCIAL_READY"
    report_path = pathlib.Path(output_path or project / "commercial_ready_report.json")
    report = {
        "generated_at": now(),
        "ready_decision": decision,
        "commercial_ready": commercial_ready,
        "promotion_decision": promotion_decision,
        "adapter_kind": adapter_kind,
        "evidence_tier": evidence_tier,
        "production_asr": bool(asr.get("production_asr")),
        "degraded": bool(asr.get("degraded", True)),
        "asr_quality_status": str(quality.get("asr_quality_status") or "not_ready"),
        "reference_transcript_coverage": coverage,
        "quality_metrics": metrics,
        "reliability_status": str(reliability_report.get("reliability_status") or "not_ready"),
        "human_review_status": review_status,
        "artifact_integrity_status": str(artifact_integrity_status).upper(),
        "delivery_status": str(delivery_status).upper(),
        "critical_blockers": blockers,
        "non_blocking_gaps": [
            "continuous_production_monitoring_required",
            "commercial_ready_gate_test_is_not_market_validation",
        ] if commercial_ready else [],
        "evidence_references": {
            "promotion_report": promotion_report.get("report_path", "production_asr_verification_report.json"),
            "reliability_report": "production_reliability_report.json",
            "human_review_evidence": "human_review_evidence.json" if human_review_evidence else "",
        },
        "thresholds": limits,
        "gate_test_only": bool(gate_test_only),
        "report_path": report_path.name if report_path.parent.resolve() == project.resolve() else str(report_path),
        "reason": (
            "All independent COMMERCIAL_READY evidence requirements passed."
            if commercial_ready
            else "COMMERCIAL_READY evidence is incomplete; candidate or delivery success alone is insufficient."
        ),
    }
    write_json(report_path, report)
    return report
