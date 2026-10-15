#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import zipfile
from typing import Any


REQUIREMENT_ARTIFACTS = [
    "customer_goal_brief.md",
    "need_interpretations.json",
    "candidate_requirements.json",
    "requirement_scorecard.json",
    "selected_requirement.json",
    "rejected_requirements.md",
    "mvp_scope.md",
    "non_goals.md",
    "acceptance_contract.json",
    "customer_decision_summary.md",
]

PRODUCT_CONTRACT_DOCS = [
    "product_brief.md",
    "technical_plan.md",
    "interaction_design.md",
    "acceptance_matrix.md",
]

DELIVERY_EVIDENCE_FILES = [
    "README.md",
    "TEST_REPORT.md",
    "DELIVERY_NOTES.md",
    "final_project_bundle.zip",
    "delivery_manifest.json",
]

IMPLEMENTATION_MARKERS = [
    "orchestrator.py",
    "stages.py",
    "cli.py",
    "gui_app.py",
]


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def read_text(path: pathlib.Path, limit: int = 80000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def file_ok(path: pathlib.Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def requirement_evidence(run_dir: pathlib.Path) -> dict[str, Any]:
    req_dir = run_dir / "requirement_decision"
    missing = [name for name in REQUIREMENT_ARTIFACTS if not file_ok(req_dir / name)]
    return {
        "status": "PASS" if not missing else "FAIL",
        "directory": str(req_dir),
        "checked": list(REQUIREMENT_ARTIFACTS),
        "missing": missing,
    }


def product_contract_evidence(project_dir: pathlib.Path) -> dict[str, Any]:
    missing = [name for name in PRODUCT_CONTRACT_DOCS if not file_ok(project_dir / name)]
    traceable = []
    for name in PRODUCT_CONTRACT_DOCS:
        text = read_text(project_dir / name).lower()
        traceable.append("selected_requirement.json" in text or "acceptance_contract.json" in text)
    return {
        "status": "PASS" if not missing and all(traceable) else "FAIL",
        "checked": list(PRODUCT_CONTRACT_DOCS),
        "missing": missing,
        "traceable_to_requirement_decision": all(traceable),
    }


def implementation_evidence(project_dir: pathlib.Path) -> dict[str, Any]:
    missing = [name for name in IMPLEMENTATION_MARKERS if not file_ok(project_dir / name)]
    cli = read_text(project_dir / "cli.py")
    gui = read_text(project_dir / "gui_app.py")
    stage_artifacts = [
        "stage_plan.json",
        "media_manifest.json",
        "audio_chunk_manifest.json",
        "transcript_merged.json",
        "segment_analysis.json",
        "selected_segments.json",
        "clip_manifest.json",
        "export_results.json",
    ]
    missing_artifacts = [name for name in stage_artifacts if not file_ok(project_dir / name)]
    return {
        "status": "PASS" if not missing and not missing_artifacts and "orchestrator" in cli and "orchestrator" in gui else "FAIL",
        "checked": list(IMPLEMENTATION_MARKERS),
        "missing": missing,
        "shared_gui_cli_core": "orchestrator" in cli and "orchestrator" in gui,
        "stage_artifacts_checked": stage_artifacts,
        "stage_artifacts_missing": missing_artifacts,
        "artifact_schema_and_traceability": not missing_artifacts,
    }


def _zip_readable(path: pathlib.Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return bool(zf.namelist())
    except Exception:
        return False


def delivery_evidence(project_dir: pathlib.Path, trial_result: dict[str, Any]) -> dict[str, Any]:
    manifest = read_json(project_dir / "delivery_manifest.json")
    screenshot_raw = (
        trial_result.get("delivery", {}).get("screenshot", {}).get("path")
        or trial_result.get("artifact_integrity", {}).get("screenshot_path")
        or manifest.get("screenshot_path")
        or ""
    )
    screenshot_path = pathlib.Path(str(screenshot_raw)) if str(screenshot_raw).strip() else None
    smoke = trial_result.get("delivery", {}).get("smoke_command", {})
    smoke_log = project_dir / "run_logs" / "delivery_smoke_command.log"
    missing = [name for name in DELIVERY_EVIDENCE_FILES if not file_ok(project_dir / name)]
    test_report = read_text(project_dir / "TEST_REPORT.md").lower()
    delivery_notes = read_text(project_dir / "DELIVERY_NOTES.md").lower()
    screenshot_ok = file_ok(screenshot_path) if screenshot_path else False
    zip_ok = file_ok(project_dir / "final_project_bundle.zip") and _zip_readable(project_dir / "final_project_bundle.zip")
    return {
        "status": "PASS" if not missing and screenshot_ok and zip_ok and smoke.get("status") == "PASS" else "FAIL",
        "checked": list(DELIVERY_EVIDENCE_FILES) + ["screenshot", "smoke log", "artifact integrity result"],
        "missing": missing,
        "screenshot_path": str(screenshot_path) if screenshot_ok and screenshot_path else "",
        "screenshot_ok": screenshot_ok,
        "zip_path": str(project_dir / "final_project_bundle.zip"),
        "zip_ok": zip_ok,
        "test_report_ok": file_ok(project_dir / "TEST_REPORT.md"),
        "delivery_notes_ok": file_ok(project_dir / "DELIVERY_NOTES.md"),
        "test_report_has_commands": "commands_run" in test_report and "no test executed" not in test_report,
        "delivery_notes_mentions_degraded": "degraded" in delivery_notes,
        "smoke_status": smoke.get("status", ""),
        "smoke_log": str(smoke_log) if file_ok(smoke_log) else "",
        "artifact_integrity_status": trial_result.get("artifact_integrity", {}).get("status", ""),
    }


def capability_evidence(project_dir: pathlib.Path, trial_result: dict[str, Any]) -> dict[str, Any]:
    capability = trial_result.get("capability_manifest", {})
    manifest_path = project_dir / "capability_manifest.json"
    text = "\n".join(
        [
            read_text(project_dir / "README.md"),
            read_text(project_dir / "TEST_REPORT.md"),
            read_text(project_dir / "DELIVERY_NOTES.md"),
        ]
    ).lower()
    degraded_tokens = ["degraded", "placeholder", "fixture", "contract_fixture", "not production", "not production asr", "commercial_ready: false"]
    visible_tokens = [token for token in degraded_tokens if token in text]
    asr_tier = str(capability.get("asr_evidence_tier", "none"))
    asr_status = str(capability.get("asr_status", ""))
    return {
        "status": "PASS" if file_ok(manifest_path) and capability.get("status") == "PASS" and len(visible_tokens) >= 2 else "FAIL",
        "manifest_path": str(manifest_path) if file_ok(manifest_path) else "",
        "local_media_adapter_status": capability.get("selected_adapter", ""),
        "ffprobe_status": capability.get("ffprobe_status", ""),
        "ffmpeg_status": capability.get("ffmpeg_status", ""),
        "media_decode_status": capability.get("media_decode_status", ""),
        "transcription_status": capability.get("transcription_status", ""),
        "asr_status": asr_status,
        "asr_evidence_tier": asr_tier,
        "asr_quality_report": capability.get("asr_quality_report_path", ""),
        "commercial_promotion_report": capability.get("commercial_promotion_report_path", ""),
        "commercial_ready_report": capability.get("commercial_ready_report_path", ""),
        "degraded_capabilities_customer_visible": len(visible_tokens) >= 2,
        "visible_degraded_tokens": visible_tokens,
        "production_asr_claimed": capability.get("asr_production_asr") is True or asr_status == "production_asr_verified",
    }


def commercial_status(trial_result: dict[str, Any]) -> dict[str, Any]:
    commercial = trial_result.get("commercial_readiness", {})
    capability = trial_result.get("capability_manifest", {})
    ready = bool(commercial.get("commercial_ready") is True or capability.get("commercial_ready") is True)
    status = str(commercial.get("status") or capability.get("commercial_readiness_level") or "COMMERCIAL_BETA")
    return {
        "status": status,
        "commercial_ready": ready,
        "ready_decision": commercial.get("ready_decision", capability.get("commercial_ready_decision", "NOT_READY")),
        "why_not_commercial_ready": commercial.get("reason")
        or "Customer acceptance verifies this trial's scoped delivery evidence, not production reliability, real ASR quality, human review, or release operations.",
        "customer_acceptance_is_not_commercial_ready": True,
    }


def score_customer_journey(
    *,
    trial_result: dict[str, Any],
    dialogue: list[dict[str, Any]],
    rework_completed: bool,
) -> dict[str, Any]:
    project_dir = pathlib.Path(str(trial_result.get("generated_project_path", "")))
    run_dir = pathlib.Path(str(trial_result.get("run_dir", "")))
    req = requirement_evidence(run_dir)
    product = product_contract_evidence(project_dir)
    implementation = implementation_evidence(project_dir)
    delivery = delivery_evidence(project_dir, trial_result)
    capability = capability_evidence(project_dir, trial_result)
    commercial = commercial_status(trial_result)
    selected = trial_result.get("selected_requirement", {})
    non_goals = selected.get("non_goals", [])
    mvp_scope = selected.get("mvp_scope", [])

    parts = {
        "requirement_discovery_quality": 15 if req["status"] == "PASS" else 0,
        "requirement_decision_usefulness": 15 if selected.get("selected_requirement_id") and req["status"] == "PASS" else 0,
        "scope_mvp_non_goals_clarity": 10 if mvp_scope and non_goals else 0,
        "product_contract_clarity": 10 if product["status"] == "PASS" else 0,
        "generated_project_usefulness": 10 if implementation["status"] == "PASS" else 0,
        "delivery_evidence_completeness": 10 if delivery["status"] == "PASS" else 0,
        "customer_facing_explanation_quality": 10 if capability["degraded_capabilities_customer_visible"] else 0,
        "rework_responsiveness": 10 if rework_completed else 0,
        "honesty_about_degraded_commercial_readiness": 10 if capability["degraded_capabilities_customer_visible"] and commercial["commercial_ready"] is False else 0,
    }
    if not delivery["test_report_ok"]:
        parts["delivery_evidence_completeness"] = max(0, parts["delivery_evidence_completeness"] - 4)
    if not delivery["delivery_notes_ok"]:
        parts["delivery_evidence_completeness"] = max(0, parts["delivery_evidence_completeness"] - 4)
    if capability["production_asr_claimed"] and capability["asr_evidence_tier"] in {"none", "placeholder", "contract_fixture"}:
        parts["honesty_about_degraded_commercial_readiness"] = 0

    total = sum(parts.values())
    blockers: list[str] = []
    if not delivery["screenshot_ok"]:
        blockers.append("screenshot_missing")
    if not delivery["zip_ok"]:
        blockers.append("zip_missing")
    if not delivery["test_report_ok"]:
        blockers.append("TEST_REPORT.md_missing")
    if not delivery["delivery_notes_ok"]:
        blockers.append("DELIVERY_NOTES.md_missing")
    if capability["status"] != "PASS":
        blockers.append("capability_evidence_incomplete")

    if total >= 90:
        verdict = "CUSTOMER_ACCEPTED"
    elif total >= 75:
        verdict = "CUSTOMER_ACCEPTED_WITH_GAPS"
    elif total >= 55:
        verdict = "NEEDS_REWORK"
    else:
        verdict = "CUSTOMER_REJECTED"
    if {"screenshot_missing", "zip_missing"} & set(blockers) and verdict == "CUSTOMER_ACCEPTED":
        verdict = "CUSTOMER_ACCEPTED_WITH_GAPS"
    if {"screenshot_missing", "zip_missing"} & set(blockers) and total < 90:
        verdict = "NEEDS_REWORK" if total >= 55 else "CUSTOMER_REJECTED"

    challenge_events = [entry for entry in dialogue if entry.get("actor") == "customer" and "challenge" in entry.get("event", "")]
    rework_events = [entry for entry in dialogue if entry.get("event") == "customer_requests_rework"]
    return {
        "total": total,
        "verdict": verdict,
        "parts": parts,
        "blockers": blockers,
        "customer_challenge_count": len(challenge_events),
        "rework_request_count": len(rework_events),
        "requirement_evidence": req,
        "product_contract_evidence": product,
        "implementation_evidence": implementation,
        "delivery_evidence": delivery,
        "capability_evidence": capability,
        "commercial_readiness": commercial,
    }
