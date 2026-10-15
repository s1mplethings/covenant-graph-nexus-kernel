from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

try:
    import asr_reference_transcript_eval
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import asr_reference_transcript_eval


READINESS_LEVELS = {
    "COMMERCIAL_BETA",
    "COMMERCIAL_BETA_PLUS",
    "COMMERCIAL_CANDIDATE",
    "COMMERCIAL_READY",
}
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "min_samples": 3,
    "min_success_rate": 0.95,
    "min_reference_coverage": 1.0,
    "max_token_error_rate": 0.25,
    "max_character_error_rate": 0.20,
    "max_timeout_count": 0,
    "max_invalid_output_count": 0,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_thresholds(thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(DEFAULT_THRESHOLDS)
    values.update(thresholds or {})
    values["min_samples"] = max(1, int(values["min_samples"]))
    for key in ("min_success_rate", "min_reference_coverage"):
        values[key] = max(0.0, min(1.0, float(values[key])))
    for key in ("max_token_error_rate", "max_character_error_rate"):
        values[key] = max(0.0, float(values[key]))
    values["max_timeout_count"] = max(0, int(values["max_timeout_count"]))
    values["max_invalid_output_count"] = max(0, int(values["max_invalid_output_count"]))
    return values


def evaluate(
    *,
    project_dir: pathlib.Path,
    capability_manifest: dict[str, Any],
    delivery_integrity_status: str,
    reference_manifest_path: pathlib.Path | None = None,
    output_path: pathlib.Path | None = None,
    human_review_status: str = "not_reviewed",
    thresholds: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    capabilities = capability_manifest.get("capabilities", {}) if isinstance(capability_manifest.get("capabilities"), dict) else {}
    asr = capabilities.get("asr", {}) if isinstance(capabilities.get("asr"), dict) else {}
    quality = capabilities.get("asr_quality", {}) if isinstance(capabilities.get("asr_quality"), dict) else {}
    decode = capabilities.get("media_decode", {}) if isinstance(capabilities.get("media_decode"), dict) else {}
    user_media = capabilities.get("user_media_input", {}) if isinstance(capabilities.get("user_media_input"), dict) else {}
    normalized_thresholds = normalize_thresholds(thresholds)
    reference_eval = asr_reference_transcript_eval.evaluate(
        project_dir=project,
        manifest_path=reference_manifest_path,
        sample_results=quality.get("sample_results", []) if isinstance(quality.get("sample_results"), list) else [],
    )
    adapter_kind = str(quality.get("adapter_kind") or asr.get("adapter_kind") or "none")
    evidence_tier = str(quality.get("evidence_tier") or asr.get("evidence_tier") or "none")
    quality_status = str(quality.get("asr_quality_status") or "not_ready")
    quality_metrics = dict(reference_eval.get("quality_metrics", {}))
    blockers: list[str] = []
    if not enabled:
        blockers.append("commercial_promotion_gate_not_requested")
    if adapter_kind == "none" and quality_status == "not_ready":
        blockers.append("missing_real_asr_command")
    if adapter_kind != "real_local_asr":
        blockers.append("fixture_or_non_real_asr_adapter")
    if evidence_tier in {"none", "placeholder", "contract_fixture", "single_sample_real"}:
        blockers.append(f"asr_evidence_tier_not_candidate:{evidence_tier}")
    if quality_status != "production_candidate" or quality.get("production_candidate") is not True:
        blockers.append(f"asr_quality_not_production_candidate:{quality_status}")
    if int(quality.get("sample_count", 0) or 0) < normalized_thresholds["min_samples"]:
        blockers.append("sample_count_below_promotion_threshold")
    if float(quality.get("success_rate", 0.0) or 0.0) < normalized_thresholds["min_success_rate"]:
        blockers.append("success_rate_below_promotion_threshold")
    if int(quality.get("timeout_samples", 0) or 0) > normalized_thresholds["max_timeout_count"]:
        blockers.append("timeout_count_above_promotion_threshold")
    if int(quality.get("invalid_output_samples", 0) or 0) > normalized_thresholds["max_invalid_output_count"]:
        blockers.append("invalid_output_count_above_promotion_threshold")
    if any(item.get("schema_valid") is not True for item in quality.get("sample_results", []) or []):
        blockers.append("transcript_schema_validation_failed")
    coverage = float(reference_eval.get("reference_transcript_coverage", 0.0) or 0.0)
    if coverage < normalized_thresholds["min_reference_coverage"]:
        blockers.append("missing_reference_transcripts" if coverage == 0.0 else "reference_transcript_coverage_below_threshold")
    token_error_rate = quality_metrics.get("token_error_rate")
    character_error_rate = quality_metrics.get("character_error_rate")
    if token_error_rate is None or float(token_error_rate) > normalized_thresholds["max_token_error_rate"]:
        blockers.append("token_error_rate_above_threshold" if token_error_rate is not None else "token_error_rate_unavailable")
    if character_error_rate is None or float(character_error_rate) > normalized_thresholds["max_character_error_rate"]:
        blockers.append("character_error_rate_above_threshold" if character_error_rate is not None else "character_error_rate_unavailable")
    if reference_eval.get("status") != "PASS":
        blockers.extend(str(item) for item in reference_eval.get("blockers", []) or [])
    if str(user_media.get("status") or "not_configured") != "verified":
        blockers.append("user_media_input_not_verified")
    if str(decode.get("status") or "not_attempted") != "verified":
        blockers.append("production_decode_evidence_missing")
    if str(delivery_integrity_status).upper() != "PASS":
        blockers.append("delivery_integrity_not_pass")
    if asr.get("degraded") is not False:
        blockers.append("asr_path_degraded")
    blockers = list(dict.fromkeys(blockers))
    fixture_evidence = adapter_kind in {"fixture", "contract_fixture"} or evidence_tier == "contract_fixture" or quality_status == "contract_only"
    if not blockers:
        decision = "COMMERCIAL_CANDIDATE"
    elif enabled and fixture_evidence and int(quality.get("successful_samples", 0) or 0) > 0:
        decision = "COMMERCIAL_BETA_PLUS"
    else:
        decision = "COMMERCIAL_BETA"
    path = pathlib.Path(output_path or project / "production_asr_verification_report.json")
    report = {
        "generated_at": now(),
        "adapter_kind": adapter_kind,
        "evidence_tier": evidence_tier,
        "asr_quality_status": quality_status,
        "production_candidate": bool(quality.get("production_candidate")),
        "production_verified": bool(quality.get("production_verified")),
        "sample_count": int(quality.get("sample_count", 0) or 0),
        "successful_samples": int(quality.get("successful_samples", 0) or 0),
        "failed_samples": int(quality.get("failed_samples", 0) or 0),
        "timeout_samples": int(quality.get("timeout_samples", 0) or 0),
        "invalid_output_samples": int(quality.get("invalid_output_samples", 0) or 0),
        "success_rate": float(quality.get("success_rate", 0.0) or 0.0),
        "non_empty_text_rate": float(quality.get("non_empty_text_rate", 0.0) or 0.0),
        "non_empty_segments_rate": float(quality.get("non_empty_segments_rate", 0.0) or 0.0),
        "reference_transcript_coverage": coverage,
        "quality_metrics": quality_metrics,
        "human_review_status": human_review_status if human_review_status != "not_reviewed" else (
            "reference_transcripts_verified" if reference_eval.get("status") == "PASS" else "not_reviewed"
        ),
        "production_decode_status": str(decode.get("status") or "not_attempted"),
        "user_media_input_status": str(user_media.get("status") or "not_configured"),
        "delivery_integrity_status": str(delivery_integrity_status).upper(),
        "promotion_decision": decision,
        "readiness_level": decision,
        "promotion_blockers": blockers,
        "non_blocking_ready_gaps": [
            "commercial_ready_requires_separate_ready_gate",
            "production_scale_reliability_review_pending",
        ] if decision == "COMMERCIAL_CANDIDATE" else [],
        "thresholds": normalized_thresholds,
        "reference_transcript_evaluation": reference_eval,
        "report_path": path.name if path.parent.resolve() == project.resolve() else str(path),
        "commercial_ready": False,
        "reason": (
            "All COMMERCIAL_CANDIDATE conditions passed; COMMERCIAL_READY requires a separate stricter gate."
            if decision == "COMMERCIAL_CANDIDATE"
            else "Promotion remains below COMMERCIAL_CANDIDATE because required production ASR evidence is incomplete."
        ),
    }
    write_json(path, report)
    return report
