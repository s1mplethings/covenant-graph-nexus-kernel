from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import local_media_adapter

try:
    import asr_evidence_tier
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import asr_evidence_tier


VALID_SELECTED = {"fixture_degraded", "python_wave_verified", "local_tool_verified", "local_tool_unavailable"}


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def check(path: pathlib.Path, *, project_dir: pathlib.Path | None = None) -> dict[str, Any]:
    manifest = read_json(path)
    blockers: list[str] = []
    if not manifest:
        blockers.append("capability_manifest_missing_or_invalid_json")
        return {"status": "FAIL", "blockers": blockers}

    selected = manifest.get("selected_adapter")
    if selected not in VALID_SELECTED:
        blockers.append("selected_adapter_invalid")
    if manifest.get("commercial_ready") not in {False, True}:
        blockers.append("commercial_ready_must_be_boolean")
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        blockers.append("capabilities_missing")
        capabilities = {}
    for name in ("media_fixture", "media_metadata", "audio_extract", "media_decode", "asr", "asr_quality", "transcription", "analysis"):
        if not isinstance(capabilities.get(name), dict):
            blockers.append(f"{name}_missing")

    fixture = capabilities.get("media_fixture", {}) if isinstance(capabilities, dict) else {}
    fixture_path = pathlib.Path(str(fixture.get("path", "")))
    if project_dir and fixture_path and not fixture_path.is_absolute():
        fixture_path = project_dir / fixture_path
    if not fixture_path.exists():
        blockers.append("media_fixture_file_missing")
    else:
        if fixture.get("sha256") != local_media_adapter.sha256(fixture_path):
            blockers.append("media_fixture_sha256_mismatch")
        if int(fixture.get("size", -1) or -1) != fixture_path.stat().st_size:
            blockers.append("media_fixture_size_mismatch")

    metadata = capabilities.get("media_metadata", {}) if isinstance(capabilities, dict) else {}
    if metadata.get("status") not in {"python_wave_verified", "ffprobe_verified", "fixture", "unavailable"}:
        blockers.append("media_metadata_status_invalid")
    if metadata.get("status") in {"python_wave_verified", "ffprobe_verified"} and not metadata.get("evidence"):
        blockers.append("media_metadata_evidence_missing")

    transcription = capabilities.get("transcription", {}) if isinstance(capabilities, dict) else {}
    if transcription.get("status") not in {"local_model_unavailable", "placeholder_transcription", "local_model_configured", "local_model_verified", "failed"}:
        blockers.append("transcription_status_invalid")
    if transcription.get("status") != "local_model_verified" and (
        transcription.get("tool") not in {"none", None} or transcription.get("model") is not None
    ):
        blockers.append("transcription_claims_real_model")
    if transcription.get("status") == "local_model_verified":
        artifact = transcription.get("artifact", {}) if isinstance(transcription.get("artifact"), dict) else {}
        output_path = pathlib.Path(str(transcription.get("output_artifact", "")))
        if project_dir and output_path and not output_path.is_absolute():
            output_path = project_dir / output_path
        if not output_path.exists():
            blockers.append("transcription_output_missing")
        else:
            if artifact.get("sha256") != local_media_adapter.sha256(output_path):
                blockers.append("transcription_output_sha256_mismatch")
            if int(artifact.get("size", -1) or -1) != output_path.stat().st_size:
                blockers.append("transcription_output_size_mismatch")
    if transcription.get("commercial_ready") is not False:
        blockers.append("transcription_commercial_ready_must_remain_false")

    user_media = capabilities.get("user_media_input", {}) if isinstance(capabilities, dict) else {}
    if user_media:
        if user_media.get("source") != "real_user_media_input":
            blockers.append("user_media_source_invalid")
        if user_media.get("commercial_ready") is not False:
            blockers.append("user_media_commercial_ready_must_remain_false")
        user_path = pathlib.Path(str(user_media.get("safe_input_path") or user_media.get("path", "")))
        if project_dir and user_path and not user_path.is_absolute():
            user_path = project_dir / user_path
        if not user_path.exists() or not user_path.is_file():
            blockers.append("user_media_file_missing")
        else:
            if user_media.get("sha256") != local_media_adapter.sha256(user_path):
                blockers.append("user_media_sha256_mismatch")
            if int(user_media.get("size", -1) or -1) != user_path.stat().st_size:
                blockers.append("user_media_size_mismatch")
        if user_media.get("metadata_status") not in {"python_wave_verified", "ffprobe_verified", "local_tool_unavailable", "invalid_media"}:
            blockers.append("user_media_metadata_status_invalid")
        if not user_media.get("media_manifest"):
            blockers.append("user_media_media_manifest_missing")

    media_decode = capabilities.get("media_decode", {}) if isinstance(capabilities, dict) else {}
    if media_decode:
        if media_decode.get("status") not in {"verified", "unavailable", "failed", "not_attempted"}:
            blockers.append("media_decode_status_invalid")
        if media_decode.get("commercial_ready") is not False:
            blockers.append("media_decode_commercial_ready_must_remain_false")
        if media_decode.get("status") == "verified":
            artifact_path = pathlib.Path(str(media_decode.get("artifact_path", "")))
            output_path = pathlib.Path(str(media_decode.get("output_path", "")))
            if project_dir:
                if artifact_path and not artifact_path.is_absolute():
                    artifact_path = project_dir / artifact_path
                if output_path and not output_path.is_absolute():
                    output_path = project_dir / output_path
            if not artifact_path.exists() or not artifact_path.is_file():
                blockers.append("media_decode_artifact_missing")
            if not output_path.exists() or not output_path.is_file() or output_path.stat().st_size <= 0:
                blockers.append("media_decode_output_missing_or_empty")
            else:
                if media_decode.get("sha256") != local_media_adapter.sha256(output_path):
                    blockers.append("media_decode_output_sha256_mismatch")
                if int(media_decode.get("size", -1) or -1) != output_path.stat().st_size:
                    blockers.append("media_decode_output_size_mismatch")
        if media_decode.get("status") != "verified" and media_decode.get("tool") == "ffmpeg" and media_decode.get("sha256"):
            blockers.append("media_decode_non_verified_claims_artifact")

    asr = capabilities.get("asr", {}) if isinstance(capabilities, dict) else {}
    if asr:
        valid_asr_statuses = {
            "no_asr_configured",
            "placeholder_transcription",
            "command_fixture_transcription",
            "asr_contract_fixture_verified",
            "real_local_asr_verified",
            "production_asr_candidate",
            "production_asr_verified",
            "real_asr_failed",
            "real_asr_timeout",
            "real_asr_invalid_output",
            "asr_quality_insufficient",
        }
        if asr.get("status") not in valid_asr_statuses:
            blockers.append("asr_status_invalid")
        if asr.get("adapter_kind") not in {"none", "fixture", "contract_fixture", "real_local_asr"}:
            blockers.append("asr_adapter_kind_invalid")
        if asr.get("evidence_tier") not in asr_evidence_tier.EVIDENCE_TIERS:
            blockers.append("asr_evidence_tier_invalid")
        if asr.get("commercial_ready") is not False:
            blockers.append("asr_commercial_ready_must_remain_false")
        quality_path = pathlib.Path(str(asr.get("quality_report_path", "")))
        if project_dir and quality_path and not quality_path.is_absolute():
            quality_path = project_dir / quality_path
        if not quality_path.exists() or not quality_path.is_file():
            blockers.append("asr_quality_report_missing")
        if asr.get("evidence_tier") == "contract_fixture" and asr.get("production_asr") is True:
            blockers.append("asr_contract_fixture_claims_production")
        if asr.get("status") == "asr_contract_fixture_verified":
            if asr.get("evidence_tier") != "contract_fixture":
                blockers.append("asr_contract_fixture_tier_mismatch")
            if asr.get("production_asr") is not False:
                blockers.append("asr_contract_fixture_production_asr_must_be_false")
        if asr.get("status") in {"asr_contract_fixture_verified", "real_local_asr_verified"}:
            output_path = pathlib.Path(str(asr.get("output_path", "")))
            if project_dir and output_path and not output_path.is_absolute():
                output_path = project_dir / output_path
            if not output_path.exists() or not output_path.is_file() or output_path.stat().st_size <= 0:
                blockers.append("asr_output_missing_or_empty")
            else:
                if asr.get("sha256") != local_media_adapter.sha256(output_path):
                    blockers.append("asr_output_sha256_mismatch")
                if int(asr.get("size", -1) or -1) != output_path.stat().st_size:
                    blockers.append("asr_output_size_mismatch")
            if not asr.get("input_sha256") or not asr.get("input_size"):
                blockers.append("asr_input_record_missing")
        if asr.get("status") == "real_local_asr_verified":
            if asr.get("adapter_kind") != "real_local_asr":
                blockers.append("asr_verified_adapter_kind_not_real")
            if asr.get("evidence_tier") != "single_sample_real":
                blockers.append("asr_real_local_tier_mismatch")
            if asr.get("production_asr") is not False:
                blockers.append("asr_single_sample_production_asr_must_be_false")
            if asr.get("degraded") is not False:
                blockers.append("asr_verified_degraded_not_false")
            if asr.get("schema_valid") is not True:
                blockers.append("asr_verified_schema_not_valid")
            if not asr.get("engine") and not asr.get("model_name"):
                blockers.append("asr_engine_or_model_name_missing")
        if asr.get("status") == "production_asr_candidate":
            if asr.get("adapter_kind") != "real_local_asr":
                blockers.append("asr_candidate_adapter_kind_not_real")
            if asr.get("evidence_tier") != "production_candidate":
                blockers.append("asr_candidate_tier_mismatch")
            if asr.get("commercial_ready") is not False:
                blockers.append("asr_candidate_commercial_ready_must_remain_false")
        if asr.get("status") not in {"production_asr_candidate", "production_asr_verified"} and asr.get("production_asr") is True:
            blockers.append("asr_non_verified_claims_production")

    asr_quality = capabilities.get("asr_quality", {}) if isinstance(capabilities, dict) else {}
    if asr_quality:
        valid_quality_statuses = {
            "not_ready",
            "contract_only",
            "single_sample_only",
            "multi_sample_candidate",
            "production_candidate",
            "failed",
            "asr_quality_insufficient",
        }
        if asr_quality.get("asr_quality_status") not in valid_quality_statuses:
            blockers.append("asr_quality_status_invalid")
        if asr_quality.get("adapter_kind") not in {"none", "fixture", "real_local_asr"}:
            blockers.append("asr_quality_adapter_kind_invalid")
        if asr_quality.get("evidence_tier") not in asr_evidence_tier.EVIDENCE_TIERS:
            blockers.append("asr_quality_evidence_tier_invalid")
        if asr_quality.get("commercial_ready") is not False:
            blockers.append("asr_quality_commercial_ready_must_remain_false")
        if asr_quality.get("evidence_tier") == "contract_fixture" and asr_quality.get("asr_quality_status") != "contract_only":
            blockers.append("asr_quality_contract_fixture_status_invalid")
        if asr_quality.get("evidence_tier") in {"contract_fixture", "single_sample_real"} and not asr_quality.get("production_readiness_blockers"):
            blockers.append("asr_quality_blockers_missing")
        for field in (
            "sample_count",
            "successful_samples",
            "failed_samples",
            "timeout_samples",
            "invalid_output_samples",
            "success_rate",
            "non_empty_text_rate",
            "non_empty_segments_rate",
            "thresholds",
            "sample_results",
            "production_candidate",
            "production_verified",
        ):
            if field not in asr_quality:
                blockers.append(f"asr_quality_{field}_missing")
        if asr_quality.get("adapter_kind") == "fixture":
            if asr_quality.get("evidence_tier") != "contract_fixture":
                blockers.append("asr_quality_fixture_tier_mismatch")
            if asr_quality.get("production_candidate") is not False:
                blockers.append("asr_quality_fixture_claims_production_candidate")
        if asr_quality.get("production_candidate") is True:
            if asr_quality.get("adapter_kind") != "real_local_asr":
                blockers.append("asr_quality_candidate_adapter_kind_not_real")
            if asr_quality.get("evidence_tier") != "production_candidate":
                blockers.append("asr_quality_candidate_tier_mismatch")
            if int(asr_quality.get("sample_count", 0) or 0) < 3:
                blockers.append("asr_quality_candidate_sample_count_below_three")
            if asr_quality.get("production_verified") is not False:
                blockers.append("asr_quality_candidate_must_not_be_verified")
            if not asr_quality.get("production_readiness_blockers"):
                blockers.append("asr_quality_candidate_blockers_missing")

    promotion = capabilities.get("commercial_promotion", {}) if isinstance(capabilities, dict) else {}
    if promotion:
        decision = str(promotion.get("promotion_decision") or "")
        if decision not in {"COMMERCIAL_BETA", "COMMERCIAL_BETA_PLUS", "COMMERCIAL_CANDIDATE", "COMMERCIAL_READY"}:
            blockers.append("commercial_promotion_decision_invalid")
        if promotion.get("commercial_ready") is not False:
            blockers.append("commercial_promotion_ready_must_remain_false")
        report_path = pathlib.Path(str(promotion.get("report_path") or ""))
        if project_dir and report_path and not report_path.is_absolute():
            report_path = project_dir / report_path
        if not report_path.exists() or not report_path.is_file():
            blockers.append("production_asr_verification_report_missing")
        if decision == "COMMERCIAL_CANDIDATE":
            if asr_quality.get("adapter_kind") != "real_local_asr":
                blockers.append("commercial_candidate_adapter_kind_not_real")
            if asr_quality.get("production_candidate") is not True:
                blockers.append("commercial_candidate_asr_quality_not_candidate")
            if promotion.get("promotion_blockers"):
                blockers.append("commercial_candidate_has_promotion_blockers")
        if asr_quality.get("adapter_kind") == "fixture" and decision in {"COMMERCIAL_CANDIDATE", "COMMERCIAL_READY"}:
            blockers.append("fixture_cannot_trigger_commercial_candidate")

    reliability = capabilities.get("production_reliability", {}) if isinstance(capabilities, dict) else {}
    if reliability:
        if reliability.get("status") not in {"not_ready", "pass", "fail"}:
            blockers.append("production_reliability_status_invalid")
        reliability_path = pathlib.Path(str(reliability.get("report_path") or ""))
        if project_dir and reliability_path and not reliability_path.is_absolute():
            reliability_path = project_dir / reliability_path
        if not reliability_path.exists() or not reliability_path.is_file():
            blockers.append("production_reliability_report_missing")

    ready = capabilities.get("commercial_ready_gate", {}) if isinstance(capabilities, dict) else {}
    if ready:
        ready_decision = str(ready.get("ready_decision") or "")
        if ready_decision not in {"NOT_READY", "REVIEW_REQUIRED", "COMMERCIAL_CANDIDATE", "COMMERCIAL_READY"}:
            blockers.append("commercial_ready_decision_invalid")
        ready_path = pathlib.Path(str(ready.get("report_path") or ""))
        if project_dir and ready_path and not ready_path.is_absolute():
            ready_path = project_dir / ready_path
        ready_report = read_json(ready_path) if ready_path.exists() and ready_path.is_file() else {}
        if not ready_report:
            blockers.append("commercial_ready_report_missing")
        expected_ready = ready_decision == "COMMERCIAL_READY"
        if ready.get("commercial_ready") is not expected_ready or manifest.get("commercial_ready") is not expected_ready:
            blockers.append("commercial_ready_boolean_decision_mismatch")
        if expected_ready:
            if asr_quality.get("adapter_kind") != "real_local_asr":
                blockers.append("commercial_ready_adapter_kind_not_real")
            if asr_quality.get("evidence_tier") not in {"production_candidate", "production_verified"}:
                blockers.append("commercial_ready_evidence_tier_insufficient")
            if reliability.get("status") != "pass":
                blockers.append("commercial_ready_reliability_not_pass")
            if ready.get("critical_blockers"):
                blockers.append("commercial_ready_has_critical_blockers")
            if promotion.get("promotion_decision") != "COMMERCIAL_CANDIDATE":
                blockers.append("commercial_ready_promotion_not_candidate")
        if asr_quality.get("adapter_kind") == "fixture" and expected_ready:
            blockers.append("fixture_cannot_trigger_commercial_ready")
    elif manifest.get("commercial_ready") is True:
        blockers.append("commercial_ready_true_without_ready_gate")

    return {"status": "PASS" if not blockers else "FAIL", "blockers": blockers, "selected_adapter": selected}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--project-dir", default="")
    args = parser.parse_args()
    result = check(pathlib.Path(args.manifest), project_dir=pathlib.Path(args.project_dir) if args.project_dir else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
