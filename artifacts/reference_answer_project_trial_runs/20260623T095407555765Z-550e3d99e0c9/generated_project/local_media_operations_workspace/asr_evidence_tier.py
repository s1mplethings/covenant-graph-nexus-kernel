from __future__ import annotations

from typing import Any


EVIDENCE_TIERS = {
    "none",
    "placeholder",
    "contract_fixture",
    "single_sample_real",
    "multi_sample_real",
    "production_candidate",
    "production_verified",
}

ASR_STATUSES = {
    "no_asr_configured",
    "placeholder_transcription",
    "command_fixture_transcription",
    "asr_contract_fixture_verified",
    "real_local_asr_verified",
    "production_asr_verified",
    "production_asr_candidate",
    "real_asr_failed",
    "real_asr_timeout",
    "real_asr_invalid_output",
    "asr_quality_insufficient",
}


def is_contract_fixture(transcript: dict[str, Any], run: dict[str, Any] | None = None) -> bool:
    engine = str(transcript.get("engine") or "").lower()
    model = str(transcript.get("model_name") or "").lower()
    evidence = transcript.get("evidence", [])
    run_text = ""
    if run:
        run_text = f"{run.get('stdout', '')} {run.get('stderr', '')}".lower()
    return (
        transcript.get("contract_test_fixture") is True
        or "contract_fixture" in engine
        or "contract-fixture" in model
        or "contract test fixture" in str(evidence).lower()
        or "contract_test_fixture" in run_text
    )


def tier_for_status(status: str) -> str:
    if status == "placeholder_transcription":
        return "placeholder"
    if status in {"command_fixture_transcription", "asr_contract_fixture_verified"}:
        return "contract_fixture"
    if status == "real_local_asr_verified":
        return "single_sample_real"
    if status == "production_asr_candidate":
        return "production_candidate"
    if status == "production_asr_verified":
        return "production_verified"
    return "none"


def normalize_section(section: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(section)
    status = str(normalized.get("status") or "no_asr_configured")
    tier = str(normalized.get("evidence_tier") or tier_for_status(status))
    if tier not in EVIDENCE_TIERS:
        tier = "none"
    normalized["evidence_tier"] = tier
    normalized["commercial_ready"] = False
    if tier in {"none", "placeholder", "contract_fixture", "single_sample_real", "multi_sample_real"}:
        normalized["production_asr"] = False
    if tier == "contract_fixture":
        normalized["status"] = "asr_contract_fixture_verified" if status not in {"command_fixture_transcription"} else status
        normalized["degraded"] = True
    return normalized


def production_readiness_blockers(section: dict[str, Any], quality_report: dict[str, Any] | None = None) -> list[str]:
    blockers: list[str] = []
    tier = str(section.get("evidence_tier") or tier_for_status(str(section.get("status") or "")))
    if tier in {"none", "placeholder"}:
        blockers.append("no_real_asr_evidence")
    if tier == "contract_fixture":
        blockers.append("contract_fixture_is_not_production_asr")
    if tier == "single_sample_real":
        blockers.append("single_sample_real_asr_is_not_production_evidence")
    if quality_report:
        status = str(quality_report.get("asr_quality_status") or "")
        if status not in {"production_candidate"}:
            blockers.append(f"asr_quality_status_not_production_candidate:{status or 'missing'}")
        for item in quality_report.get("production_readiness_blockers", []) or []:
            text = str(item)
            if text and text not in blockers:
                blockers.append(text)
    return blockers
