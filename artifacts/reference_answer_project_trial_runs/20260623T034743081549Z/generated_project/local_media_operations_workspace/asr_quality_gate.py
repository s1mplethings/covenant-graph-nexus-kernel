from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

try:
    import asr_evidence_tier
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import asr_evidence_tier

try:
    import real_asr_adapter_contract
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import real_asr_adapter_contract


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _confidence_from_result(result: dict[str, Any]) -> float | None:
    output = pathlib.Path(str(result.get("output_path") or ""))
    if not output.exists():
        return None
    try:
        doc = json.loads(output.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(doc.get("confidence"), (int, float)):
        return float(doc["confidence"])
    segments = doc.get("segments")
    if isinstance(segments, list):
        values = [float(item["confidence"]) for item in segments if isinstance(item, dict) and isinstance(item.get("confidence"), (int, float))]
        if values:
            return sum(values) / len(values)
    return None


def _sample_summary(index: int, input_path: pathlib.Path, result: dict[str, Any]) -> dict[str, Any]:
    output = pathlib.Path(str(result.get("output_path") or ""))
    confidence = _confidence_from_result(result)
    status = str(result.get("status") or "no_asr_configured")
    text_length = 0
    segment_count = 0
    if output.exists():
        try:
            doc = json.loads(output.read_text(encoding="utf-8"))
            text_length = len(str(doc.get("text") or ""))
            segments = doc.get("segments")
            segment_count = len(segments) if isinstance(segments, list) else 0
        except Exception:
            pass
    return {
        "sample_index": index,
        "input_path": str(input_path),
        "input_sha256": result.get("input_sha256", ""),
        "input_size": result.get("input_size", 0),
        "status": status,
        "evidence_tier": result.get("evidence_tier", asr_evidence_tier.tier_for_status(status)),
        "returncode": result.get("returncode"),
        "timed_out": bool(result.get("timed_out")),
        "schema_valid": bool(result.get("schema_valid")),
        "schema_blockers": result.get("schema_blockers", []),
        "output_path": str(output) if output else "",
        "output_sha256": result.get("sha256", ""),
        "output_size": result.get("size", 0),
        "text_length": text_length,
        "segment_count": segment_count,
        "confidence": confidence,
    }


def _status_and_tier(sample_results: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    blockers: list[str] = []
    sample_count = len(sample_results)
    if sample_count == 0:
        return "not_ready", "none", ["no_asr_samples"]
    statuses = [str(item.get("status") or "") for item in sample_results]
    tiers = [str(item.get("evidence_tier") or "none") for item in sample_results]
    if any(item.get("timed_out") for item in sample_results):
        return "not_ready", "none", ["asr_sample_timeout"]
    if any(status == "real_asr_invalid_output" for status in statuses):
        return "failed", "none", ["asr_sample_invalid_output"]
    if any(status == "real_asr_failed" for status in statuses):
        return "failed", "none", ["asr_sample_command_failed"]
    if all(status in {"no_asr_configured", "placeholder_transcription", "command_fixture_transcription"} for status in statuses):
        tier = "placeholder" if any(status == "placeholder_transcription" for status in statuses) else "none"
        return "not_ready", tier, ["no_real_asr_command_configured"]
    if any(item.get("text_length", 0) <= 0 or item.get("segment_count", 0) <= 0 for item in sample_results):
        return "failed", "none", ["asr_quality_insufficient_empty_text_or_segments"]
    if all(tier == "contract_fixture" for tier in tiers):
        return "contract_only", "contract_fixture", ["contract_fixture_is_not_production_asr"]
    if all(tier in {"single_sample_real", "multi_sample_real"} for tier in tiers):
        if sample_count >= 2:
            blockers.append("multi_sample_real_asr_needs_quality_thresholds_and_human_review")
            return "multi_sample_candidate", "multi_sample_real", blockers
        return "single_sample_only", "single_sample_real", ["single_sample_real_asr_is_not_production_evidence"]
    if all(tier == "production_candidate" for tier in tiers):
        return "production_candidate", "production_candidate", ["production_candidate_requires_separate_commercial_gate"]
    return "not_ready", "none", ["mixed_or_missing_asr_evidence_tiers"]


def run_quality_gate(
    *,
    project_dir: pathlib.Path,
    sample_paths: list[pathlib.Path],
    output_path: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    report_path = pathlib.Path(output_path or project / "asr_quality_report.json")
    sample_results: list[dict[str, Any]] = []
    for index, raw_sample in enumerate(sample_paths, start=1):
        sample = pathlib.Path(raw_sample)
        if not sample.is_absolute():
            sample = (project / sample).resolve()
        sample_output = project / f"asr_quality_sample_{index}.json"
        result = real_asr_adapter_contract.evaluate(
            project_dir=project,
            input_path=sample,
            output_path=sample_output,
            env=env,
            timeout=timeout,
        )
        sample_results.append(_sample_summary(index, sample, result))

    asr_quality_status, evidence_tier, blockers = _status_and_tier(sample_results)
    confidence_values = [float(item["confidence"]) for item in sample_results if isinstance(item.get("confidence"), (int, float))]
    average_confidence = round(sum(confidence_values) / len(confidence_values), 6) if confidence_values else None
    report = {
        "generated_at": now(),
        "asr_quality_status": asr_quality_status,
        "evidence_tier": evidence_tier,
        "sample_count": len(sample_results),
        "successful_samples": sum(1 for item in sample_results if item.get("status") in {"asr_contract_fixture_verified", "real_local_asr_verified", "production_asr_candidate", "production_asr_verified"}),
        "failed_samples": sum(1 for item in sample_results if item.get("status") in {"real_asr_failed", "real_asr_invalid_output", "asr_quality_insufficient"}),
        "timeout_samples": sum(1 for item in sample_results if item.get("timed_out")),
        "invalid_output_samples": sum(1 for item in sample_results if item.get("status") == "real_asr_invalid_output"),
        "non_empty_text_count": sum(1 for item in sample_results if int(item.get("text_length") or 0) > 0),
        "non_empty_segments_count": sum(1 for item in sample_results if int(item.get("segment_count") or 0) > 0),
        "average_confidence": average_confidence,
        "confidence_unavailable_reason": "" if average_confidence is not None else "no confidence values emitted by ASR command",
        "transcript_artifacts": [item.get("output_path", "") for item in sample_results if item.get("output_path")],
        "input_audio_hashes": [item.get("input_sha256", "") for item in sample_results if item.get("input_sha256")],
        "output_transcript_hashes": [item.get("output_sha256", "") for item in sample_results if item.get("output_sha256")],
        "sample_results": sample_results,
        "pass_fail_reasons": list(blockers),
        "production_readiness_blockers": list(blockers),
        "commercial_ready": False,
        "reason": "ASR quality gate evidence is not sufficient to promote commercial readiness.",
    }
    write_json(report_path, report)
    return report


def empty_report(project_dir: pathlib.Path, *, reason: str = "ASR quality gate was not configured.") -> dict[str, Any]:
    path = pathlib.Path(project_dir) / "asr_quality_report.json"
    report = {
        "generated_at": now(),
        "asr_quality_status": "not_ready",
        "evidence_tier": "none",
        "sample_count": 0,
        "successful_samples": 0,
        "failed_samples": 0,
        "timeout_samples": 0,
        "invalid_output_samples": 0,
        "non_empty_text_count": 0,
        "non_empty_segments_count": 0,
        "average_confidence": None,
        "confidence_unavailable_reason": reason,
        "transcript_artifacts": [],
        "input_audio_hashes": [],
        "output_transcript_hashes": [],
        "sample_results": [],
        "pass_fail_reasons": [reason],
        "production_readiness_blockers": [reason],
        "commercial_ready": False,
        "reason": reason,
    }
    write_json(path, report)
    return report
