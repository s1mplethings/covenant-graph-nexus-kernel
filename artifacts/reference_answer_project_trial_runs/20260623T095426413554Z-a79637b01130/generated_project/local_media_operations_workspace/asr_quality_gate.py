from __future__ import annotations

import json
import os
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


ENV_ADAPTER_KIND = "CGKN_REAL_ASR_ADAPTER_KIND"
VALID_ADAPTER_KINDS = {"none", "fixture", "real_local_asr"}
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "min_samples": 2,
    "min_success_rate": 1.0,
    "min_non_empty_text_rate": 1.0,
    "min_non_empty_segments_rate": 1.0,
    "max_timeout_count": 0,
    "max_invalid_output_count": 0,
    "require_confidence_or_reason": True,
}
SUCCESS_STATUSES = {
    "asr_contract_fixture_verified",
    "real_local_asr_verified",
    "production_asr_candidate",
    "production_asr_verified",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_transcript(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _run_evidence(result: dict[str, Any]) -> dict[str, Any]:
    for item in result.get("evidence", []) or []:
        if isinstance(item, dict) and ("duration_seconds" in item or "command" in item):
            return item
    return {}


def _sample_summary(index: int, input_path: pathlib.Path, result: dict[str, Any]) -> dict[str, Any]:
    transcript_path = pathlib.Path(str(result.get("output_path") or ""))
    transcript = _load_transcript(transcript_path)
    segments = transcript.get("segments")
    segments_non_empty = isinstance(segments, list) and bool(segments)
    text_non_empty = bool(str(transcript.get("text") or "").strip())
    confidence: float | None = None
    if isinstance(transcript.get("confidence"), (int, float)):
        confidence = float(transcript["confidence"])
    elif isinstance(segments, list):
        values = [
            float(item["confidence"])
            for item in segments
            if isinstance(item, dict) and isinstance(item.get("confidence"), (int, float))
        ]
        if values:
            confidence = sum(values) / len(values)
    confidence_reason = str(transcript.get("confidence_unavailable_reason") or "").strip()
    if confidence is None and not confidence_reason:
        confidence_reason = "ASR command did not emit confidence or an unavailable reason."
    status = str(result.get("status") or "no_asr_configured")
    run = _run_evidence(result)
    blockers = [str(item) for item in result.get("schema_blockers", []) or []]
    failure_reason = "" if status in SUCCESS_STATUSES else str(result.get("reason") or "; ".join(blockers) or status)
    return {
        "sample_index": index,
        "input_path": str(input_path),
        "input_sha256": result.get("input_sha256", ""),
        "input_size": result.get("input_size", 0),
        "command": result.get("command"),
        "returncode": result.get("returncode"),
        "timed_out": bool(result.get("timed_out")),
        "transcript_path": str(transcript_path) if str(transcript_path) != "." else "",
        "transcript_sha256": result.get("sha256", ""),
        "transcript_size": result.get("size", 0),
        "schema_valid": bool(result.get("schema_valid")),
        "text_non_empty": text_non_empty,
        "segments_non_empty": segments_non_empty,
        "confidence": confidence,
        "confidence_unavailable_reason": "" if confidence is not None else confidence_reason,
        "duration_seconds": run.get("duration_seconds", 0.0),
        "status": status,
        "failure_reason": failure_reason,
        "evidence_tier": result.get("evidence_tier", asr_evidence_tier.tier_for_status(status)),
        # Compatibility fields retained for existing report consumers.
        "output_path": str(transcript_path) if str(transcript_path) != "." else "",
        "output_sha256": result.get("sha256", ""),
        "output_size": result.get("size", 0),
        "text_length": len(str(transcript.get("text") or "")),
        "segment_count": len(segments) if isinstance(segments, list) else 0,
        "schema_blockers": blockers,
    }


def normalize_thresholds(thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(DEFAULT_THRESHOLDS)
    values.update(thresholds or {})
    values["min_samples"] = max(1, int(values["min_samples"]))
    for key in ("min_success_rate", "min_non_empty_text_rate", "min_non_empty_segments_rate"):
        values[key] = max(0.0, min(1.0, float(values[key])))
    values["max_timeout_count"] = max(0, int(values["max_timeout_count"]))
    values["max_invalid_output_count"] = max(0, int(values["max_invalid_output_count"]))
    values["require_confidence_or_reason"] = bool(values["require_confidence_or_reason"])
    return values


def _threshold_blockers(report: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    comparisons = (
        ("sample_count", "min_samples", "sample_count_below_minimum"),
        ("success_rate", "min_success_rate", "success_rate_below_threshold"),
        ("non_empty_text_rate", "min_non_empty_text_rate", "non_empty_text_rate_below_threshold"),
        ("non_empty_segments_rate", "min_non_empty_segments_rate", "non_empty_segments_rate_below_threshold"),
    )
    for actual, expected, blocker in comparisons:
        if float(report[actual]) < float(thresholds[expected]):
            blockers.append(blocker)
    if int(report["timeout_samples"]) > int(thresholds["max_timeout_count"]):
        blockers.append("timeout_count_above_threshold")
    if int(report["invalid_output_samples"]) > int(thresholds["max_invalid_output_count"]):
        blockers.append("invalid_output_count_above_threshold")
    if thresholds["require_confidence_or_reason"]:
        if any(item.get("confidence") is None and not item.get("confidence_unavailable_reason") for item in report["sample_results"]):
            blockers.append("confidence_or_unavailable_reason_missing")
    return blockers


def run_quality_gate(
    *,
    project_dir: pathlib.Path,
    sample_paths: list[pathlib.Path],
    output_path: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 2.0,
    adapter_kind: str | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    report_path = pathlib.Path(output_path or project / "asr_quality_report.json")
    effective_env = env if env is not None else os.environ
    declared_kind = str(adapter_kind or effective_env.get(ENV_ADAPTER_KIND, "")).strip()
    explicit_kind = bool(declared_kind)
    if declared_kind not in VALID_ADAPTER_KINDS:
        declared_kind = "none"
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
            env=effective_env,
            timeout=timeout,
        )
        sample_results.append(_sample_summary(index, sample, result))

    if declared_kind == "none" and sample_results:
        tiers = {str(item.get("evidence_tier") or "none") for item in sample_results}
        if tiers == {"contract_fixture"}:
            declared_kind = "fixture"
        elif tiers <= {"single_sample_real", "multi_sample_real"} and tiers != {"none"}:
            declared_kind = "real_local_asr"

    sample_count = len(sample_results)
    successful_samples = sum(1 for item in sample_results if item.get("status") in SUCCESS_STATUSES)
    timeout_samples = sum(1 for item in sample_results if item.get("timed_out"))
    invalid_output_samples = sum(1 for item in sample_results if item.get("status") == "real_asr_invalid_output")
    non_empty_text_count = sum(1 for item in sample_results if item.get("text_non_empty"))
    non_empty_segments_count = sum(1 for item in sample_results if item.get("segments_non_empty"))
    divisor = sample_count or 1
    confidence_values = [float(item["confidence"]) for item in sample_results if isinstance(item.get("confidence"), (int, float))]
    normalized_thresholds = normalize_thresholds(thresholds)
    report: dict[str, Any] = {
        "generated_at": now(),
        "adapter_kind": declared_kind,
        "evidence_tier": "none",
        "asr_quality_status": "not_ready",
        "production_candidate": False,
        "production_verified": False,
        "commercial_ready": False,
        "sample_count": sample_count,
        "successful_samples": successful_samples,
        "failed_samples": sample_count - successful_samples,
        "timeout_samples": timeout_samples,
        "invalid_output_samples": invalid_output_samples,
        "success_rate": round(successful_samples / divisor, 6) if sample_count else 0.0,
        "non_empty_text_rate": round(non_empty_text_count / divisor, 6) if sample_count else 0.0,
        "non_empty_segments_rate": round(non_empty_segments_count / divisor, 6) if sample_count else 0.0,
        "non_empty_text_count": non_empty_text_count,
        "non_empty_segments_count": non_empty_segments_count,
        "average_confidence": round(sum(confidence_values) / len(confidence_values), 6) if confidence_values else None,
        "confidence_unavailable_reason": "" if confidence_values else "No sample emitted confidence values.",
        "thresholds": normalized_thresholds,
        "sample_results": sample_results,
        "transcript_artifacts": [item["transcript_path"] for item in sample_results if item.get("transcript_path")],
        "input_audio_hashes": [item["input_sha256"] for item in sample_results if item.get("input_sha256")],
        "output_transcript_hashes": [item["transcript_sha256"] for item in sample_results if item.get("transcript_sha256")],
        "production_readiness_blockers": [],
        "pass_fail_reasons": [],
        "quality_report_path": report_path.name,
        "reason": "",
    }

    command_configured = bool(str(effective_env.get(real_asr_adapter_contract.ENV_COMMAND, "")).strip())
    tiers = {str(item.get("evidence_tier") or "none") for item in sample_results}
    if not command_configured:
        blockers = ["no_real_asr_command_configured"]
        report["reason"] = "CGKN_REAL_ASR_CMD is not configured."
    elif declared_kind == "fixture" or tiers == {"contract_fixture"}:
        report["adapter_kind"] = "fixture"
        report["evidence_tier"] = "contract_fixture"
        report["asr_quality_status"] = "contract_only"
        blockers = ["contract_fixture_is_not_production_asr"]
        report["reason"] = "The command exercised the multi-sample evaluation contract with fixtures only."
    elif not explicit_kind and timeout_samples:
        blockers = ["asr_sample_timeout"]
        report["reason"] = "At least one bounded ASR sample timed out."
    elif not explicit_kind and any(item.get("status") in {"real_asr_failed", "real_asr_invalid_output"} for item in sample_results):
        report["asr_quality_status"] = "failed"
        blockers = ["asr_sample_invalid_output" if invalid_output_samples else "asr_sample_command_failed"]
        report["reason"] = "At least one ASR sample command or transcript failed validation."
    elif declared_kind != "real_local_asr":
        blockers = ["real_local_asr_adapter_kind_not_declared"]
        report["reason"] = "A real local ASR evaluation requires adapter_kind=real_local_asr."
    else:
        report["evidence_tier"] = "single_sample_real" if sample_count == 1 else "multi_sample_real"
        blockers = _threshold_blockers(report, normalized_thresholds)
        if blockers:
            report["asr_quality_status"] = "single_sample_only" if sample_count == 1 else "asr_quality_insufficient"
            report["reason"] = "Real local ASR samples did not satisfy all configured quality thresholds."
        elif not explicit_kind:
            report["asr_quality_status"] = "multi_sample_candidate"
            blockers = ["explicit_real_local_asr_adapter_kind_required"]
            report["reason"] = "Schema-valid multi-sample evidence exists, but the real adapter kind was not explicitly declared."
        else:
            report["asr_quality_status"] = "production_candidate"
            report["evidence_tier"] = "production_candidate"
            report["production_candidate"] = True
            blockers = [
                "production_candidate_is_not_production_verified",
                "human_transcript_quality_review_missing",
                "production_load_reliability_evidence_missing",
                "commercial_gate_not_evaluated",
            ]
            report["reason"] = "Bounded real-local-ASR samples passed configured thresholds; separate production and commercial verification is still required."

    report["production_readiness_blockers"] = blockers
    report["pass_fail_reasons"] = list(blockers)
    write_json(report_path, report)
    return report


def empty_report(
    project_dir: pathlib.Path,
    *,
    reason: str = "ASR quality gate was not configured.",
    output_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    path = pathlib.Path(output_path or project / "asr_quality_report.json")
    report = {
        "generated_at": now(),
        "adapter_kind": "none",
        "evidence_tier": "none",
        "asr_quality_status": "not_ready",
        "production_candidate": False,
        "production_verified": False,
        "commercial_ready": False,
        "sample_count": 0,
        "successful_samples": 0,
        "failed_samples": 0,
        "timeout_samples": 0,
        "invalid_output_samples": 0,
        "success_rate": 0.0,
        "non_empty_text_rate": 0.0,
        "non_empty_segments_rate": 0.0,
        "non_empty_text_count": 0,
        "non_empty_segments_count": 0,
        "average_confidence": None,
        "confidence_unavailable_reason": reason,
        "thresholds": normalize_thresholds(),
        "sample_results": [],
        "transcript_artifacts": [],
        "input_audio_hashes": [],
        "output_transcript_hashes": [],
        "production_readiness_blockers": [reason],
        "pass_fail_reasons": [reason],
        "quality_report_path": path.name,
        "reason": reason,
    }
    write_json(path, report)
    return report
