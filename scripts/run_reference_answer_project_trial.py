#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import continuous_generation_ledger
import capability_manifest_check
import delivery_evidence_builder
import discovery_selection_lane
import implementation_structure_materializer
import planning_docs_materializer
import product_acceptance
import requirement_acceptance_check
import requirement_decision_lane
import stage_artifact_schema_checker


ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"
SUMMARY_MD = ARTIFACTS_DIR / "reference_answer_trial_summary.md"
SUMMARY_JSON = ARTIFACTS_DIR / "reference_answer_trial.json"
GAP_ANALYSIS = ARTIFACTS_DIR / "reference_answer_gap_analysis.md"
REPAIR_PLAN = ARTIFACTS_DIR / "reference_answer_repair_plan.md"
LEAK_REPORT = ARTIFACTS_DIR / "reference_name_leak_report.md"
CURRENT_GAPS = ARTIFACTS_DIR / "continuous_generation_current_gaps.md"
RUNS_DIR = ARTIFACTS_DIR / "reference_answer_project_trial_runs"


def create_unique_run_dir(artifacts_dir: pathlib.Path) -> pathlib.Path:
    runs_dir = pathlib.Path(artifacts_dir) / "reference_answer_project_trial_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        candidate = runs_dir / f"{stamp}-{uuid.uuid4().hex[:12]}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("Unable to allocate a unique reference trial run directory.")

NEW_CUSTOMER_GOAL = (
    "I want a local-first media production and review workbench for individual creators "
    "or small teams. It can import video, audio, and asset files, organize a material "
    "library, define a processing workflow, generate clip or item analysis, flag candidate "
    "content worth reviewing, choose outputs, export a project package, and generate a "
    "processing report. It cannot depend on cloud services and must not pretend to have "
    "real AI models. CGKN should decide the real requirement, MVP scope, non-goals, "
    "acceptance criteria, and generate a runnable local project."
)

REFERENCE_CAPABILITIES = [
    "local_first",
    "no_cloud_core_dependency",
    "honest_degraded_mode",
    "gui_or_local_visual_interface",
    "cli",
    "shared_gui_cli_core",
    "unified_pipeline",
    "orchestrator_or_stages",
    "multi_stage_processing",
    "stage_artifacts",
    "artifact_schema",
    "artifact_traceability",
    "product_contract_docs",
    "requirement_decision_artifacts",
    "delivery_evidence",
    "layered_acceptance",
]

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

PRODUCT_DOCS = [
    "product_brief.md",
    "technical_plan.md",
    "interaction_design.md",
    "acceptance_matrix.md",
]

DELIVERY_FILES = [
    "README.md",
    "TEST_REPORT.md",
    "DELIVERY_NOTES.md",
    "final_project_bundle.zip",
    "delivery_manifest.json",
]

TEXT_SKIP_SUFFIXES = {".zip", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".pyc"}
BENIGN_UPPERCASE = {
    "CGKN",
    "CGNK",
    "GUI",
    "CLI",
    "API",
    "AI",
    "MVP",
    "README",
    "TEST",
    "REPORT",
    "DELIVERY",
    "PASS",
    "FAIL",
    "PARTIAL",
    "JSON",
    "HTTP",
    "ZIP",
    "LEGACY",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def redact_terms(terms: list[str]) -> list[dict[str, str]]:
    return [{"label": f"reference_token_{index + 1}", "sha256_12": stable_hash(term)} for index, term in enumerate(terms)]


def detect_reference_names(reference_answer: str, explicit_forbidden: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for term in explicit_forbidden or []:
        clean = str(term).strip()
        if clean and clean not in found:
            found.append(clean)

    patterns = [
        r"(?:old project name|legacy project name|old reference project name|旧项目名|旧参考项目名称)\s*[:：]\s*([A-Za-z][A-Za-z0-9_-]{2,40})",
        r"\b([A-Z][A-Z0-9]{2,12})\s*(?:相关回答|相关项目|reference answer|reference project)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, reference_answer, flags=re.I):
            token = match.group(1).strip("`'\" ，,.;:：")
            if token.upper() not in BENIGN_UPPERCASE and token not in found:
                found.append(token)
    for token in re.findall(r"\b[A-Z][A-Z0-9]{3,12}\b", reference_answer):
        if token not in BENIGN_UPPERCASE and token not in found:
            local_context = reference_answer[max(0, reference_answer.find(token) - 24) : reference_answer.find(token) + 48]
            if any(marker in local_context for marker in ("相关回答", "reference answer", "legacy project", "旧项目", "旧参考")):
                found.append(token)
    return found


def extract_reference_profile(reference_answer: str, forbidden_terms: list[str] | None = None) -> dict[str, Any]:
    text = reference_answer.lower()
    detected_forbidden = detect_reference_names(reference_answer, forbidden_terms)
    complexity = "production_scale" if any(term in text for term in ("pipeline", "artifact", "delivery", "benchmark", "工作流", "验收", "交付")) else "complex"
    workflow_depth = "multi_stage" if any(term in text for term in ("stage", "pipeline", "多阶段", "流程")) else "structured"
    return {
        "profile_id": "reference_grade_project_trial_profile",
        "created_at": now(),
        "complexity_level": complexity,
        "workflow_depth": workflow_depth,
        "required_capabilities": list(REFERENCE_CAPABILITIES),
        "required_product_docs": list(PRODUCT_DOCS),
        "required_requirement_artifacts": list(REQUIREMENT_ARTIFACTS),
        "required_delivery_evidence": list(DELIVERY_FILES) + ["screenshot", "smoke log"],
        "required_layered_statuses": [
            "requirement_decision_status",
            "product_contract_status",
            "implementation_status",
            "delivery_status",
            "artifact_integrity_status",
            "commercial_readiness_status",
            "overall_status",
        ],
        "forbidden_reference_tokens": redact_terms(detected_forbidden),
        "forbidden_reference_token_count": len(detected_forbidden),
    }


def text_files_under(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in paths:
        root = pathlib.Path(root)
        if root.is_file():
            candidates = [root]
        elif root.exists():
            candidates = [path for path in root.rglob("*") if path.is_file()]
        else:
            candidates = []
        for path in candidates:
            if path.suffix.lower() in TEXT_SKIP_SUFFIXES:
                continue
            files.append(path)
    return files


def scan_name_leaks(paths: list[pathlib.Path], forbidden_terms: list[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    terms = [term for term in forbidden_terms if str(term).strip()]
    for path in text_files_under(paths):
        text = read_text(path)
        for term in terms:
            if term and term in text:
                findings.append(
                    {
                        "path": str(path),
                        "token_hash": stable_hash(term),
                        "token_label": f"reference_token_{terms.index(term) + 1}",
                    }
                )
    return {
        "status": "FAIL" if findings else "PASS",
        "scanned_file_count": len(text_files_under(paths)),
        "forbidden_reference_token_count": len(terms),
        "findings": findings,
    }


def file_exists(path: pathlib.Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _find_project_files(project_dir: pathlib.Path) -> dict[str, bool]:
    return {name: file_exists(project_dir / name) for name in DELIVERY_FILES + PRODUCT_DOCS}


def evaluate_artifact_integrity(project_dir: pathlib.Path, run_dir: pathlib.Path) -> dict[str, Any]:
    contract = read_json(run_dir / "discovery" / "complexity_project_contract.json")
    required = [str(item) for item in contract.get("required_stage_artifacts", []) if str(item).strip()]
    stage_schema = stage_artifact_schema_checker.check(project_dir, required)
    manifest = read_json(project_dir / "delivery_manifest.json")
    screenshot = pathlib.Path(str(manifest.get("screenshot_path", "")))
    zip_path = project_dir / "final_project_bundle.zip"
    blockers: list[str] = []
    if stage_schema.get("status") != "PASS":
        blockers.extend(str(item) for item in stage_schema.get("blockers", []))
    if not zip_path.exists() or zip_path.stat().st_size <= 0:
        blockers.append("final_project_bundle.zip_missing")
    if not screenshot.exists() or screenshot.stat().st_size <= 100:
        blockers.append("screenshot_missing")
    if not file_exists(project_dir / "delivery_manifest.json"):
        blockers.append("delivery_manifest.json_missing")
    smoke = manifest.get("smoke_command", {}) if isinstance(manifest.get("smoke_command"), dict) else {}
    if smoke.get("status") != "PASS":
        blockers.append("smoke_command_failed")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "stage_artifact_schema": stage_schema,
        "blockers": blockers,
        "zip_path": str(zip_path),
        "zip_size": zip_path.stat().st_size if zip_path.exists() else 0,
        "screenshot_path": str(screenshot) if screenshot.exists() else "",
        "delivery_manifest_path": str(project_dir / "delivery_manifest.json"),
    }


def evaluate_reference_alignment(project_dir: pathlib.Path, run_dir: pathlib.Path, layered: dict[str, Any], artifact_integrity: dict[str, Any]) -> dict[str, Any]:
    contract = read_json(run_dir / "discovery" / "complexity_project_contract.json")
    selected = read_json(run_dir / "requirement_decision" / "selected_requirement.json")
    files = _find_project_files(project_dir)
    stage_artifacts = [project_dir / str(item) for item in contract.get("required_stage_artifacts", []) if str(item).strip()]
    artifact_docs = [read_json(path) for path in stage_artifacts]
    checks = {
        "local_first": "local" in json.dumps(selected, ensure_ascii=False).lower() or "本地" in json.dumps(selected, ensure_ascii=False),
        "no_cloud_core_dependency": "cloud" in " ".join(str(item).lower() for item in selected.get("non_goals", [])),
        "honest_degraded_mode": "degraded" in (read_text(project_dir / "DELIVERY_NOTES.md") + read_text(project_dir / "stages.py")).lower(),
        "gui_or_local_visual_interface": file_exists(project_dir / "gui_app.py"),
        "cli": file_exists(project_dir / "cli.py"),
        "shared_gui_cli_core": "orchestrator" in read_text(project_dir / "cli.py") and "orchestrator" in read_text(project_dir / "gui_app.py"),
        "unified_pipeline": bool(contract.get("required_pipeline_stages")),
        "orchestrator_or_stages": file_exists(project_dir / "orchestrator.py") and file_exists(project_dir / "stages.py"),
        "multi_stage_processing": len(contract.get("required_pipeline_stages", [])) >= 6,
        "stage_artifacts": all(path.exists() for path in stage_artifacts) and len(stage_artifacts) >= 6,
        "artifact_schema": artifact_integrity.get("stage_artifact_schema", {}).get("status") == "PASS",
        "artifact_traceability": all(isinstance(doc.get("upstream_artifacts"), list) for doc in artifact_docs if doc),
        "product_contract_docs": all(files.get(name) for name in PRODUCT_DOCS),
        "requirement_decision_artifacts": all(file_exists(run_dir / "requirement_decision" / name) for name in REQUIREMENT_ARTIFACTS),
        "delivery_evidence": artifact_integrity.get("status") == "PASS",
        "layered_acceptance": all(layered.get(key) == "PASS" for key in ("requirement_decision_status", "product_contract_status", "implementation_status", "delivery_status")),
    }
    passed = sum(1 for value in checks.values() if value)
    score = round(100 * passed / len(checks))
    return {
        "status": "PASS" if score >= 90 else ("PARTIAL" if score >= 75 else "FAIL"),
        "score": score,
        "checks": checks,
        "missing": [key for key, value in checks.items() if not value],
    }


def evaluate_commercial_honesty(project_dir: pathlib.Path) -> dict[str, Any]:
    notes = read_text(project_dir / "DELIVERY_NOTES.md").lower()
    readme = read_text(project_dir / "README.md").lower()
    verification = read_json(project_dir / "production_asr_verification_report.json")
    ready_report = read_json(project_dir / "commercial_ready_report.json")
    decision = str(verification.get("promotion_decision") or "COMMERCIAL_BETA")
    valid_decision = decision in {"COMMERCIAL_BETA", "COMMERCIAL_BETA_PLUS", "COMMERCIAL_CANDIDATE"}
    no_commercial_claim = (
        "commercial ready" not in readme
        and "commercial_ready: true" not in readme
        and '"commercial_ready": true' not in readme
    )
    ready_decision = str(ready_report.get("ready_decision") or "NOT_READY")
    ready_value = ready_report.get("commercial_ready") is True
    honest_ready = (ready_decision == "COMMERCIAL_READY") == ready_value
    honest_gate = valid_decision and verification.get("commercial_ready") is False and honest_ready and "commercial_candidate is not commercial_ready" in notes
    status = "COMMERCIAL_READY" if ready_value and ready_decision == "COMMERCIAL_READY" else decision
    return {
        "status": status if honest_gate and no_commercial_claim else "NEEDS_REWORK",
        "commercial_ready": ready_value,
        "honesty_status": "PASS" if honest_gate and no_commercial_claim else "FAIL",
        "promotion_blockers": verification.get("promotion_blockers", []),
        "ready_decision": ready_decision,
        "ready_blockers": ready_report.get("critical_blockers", []),
        "production_asr_verification_report": str(project_dir / "production_asr_verification_report.json"),
        "commercial_ready_report": str(project_dir / "commercial_ready_report.json"),
        "reason": ready_report.get("reason", verification.get("reason", "Commercial readiness evidence is incomplete.")),
    }


def evaluate_fixture_processing(project_dir: pathlib.Path) -> dict[str, Any]:
    fixture = project_dir / "fixtures" / "media_fixture.json"
    segment_analysis = read_json(project_dir / "segment_analysis.json")
    export = read_json(project_dir / "export_results.json")
    blockers: list[str] = []
    if not fixture.exists() or fixture.stat().st_size <= 0:
        blockers.append("fixture_missing")
    allowed_modes = {"local_fixture_processing", "local_user_media_contract"}
    if segment_analysis.get("mode") not in allowed_modes or int(segment_analysis.get("count", 0) or 0) <= 0:
        blockers.append("segment_analysis_not_fixture_backed")
    if not any(isinstance(item, dict) and item.get("candidate") for item in segment_analysis.get("items", [])):
        blockers.append("candidate_items_missing")
    if export.get("mode") not in allowed_modes or int(export.get("count", 0) or 0) <= 0:
        blockers.append("export_result_not_fixture_backed")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "fixture_path": str(fixture) if fixture.exists() else "",
        "segment_count": segment_analysis.get("count", 0),
        "export_count": export.get("count", 0),
        "blockers": blockers,
        "still_degraded": segment_analysis.get("status") == "degraded" and export.get("status") == "degraded",
        "mode": segment_analysis.get("mode", ""),
    }


def evaluate_capability_manifest(project_dir: pathlib.Path) -> dict[str, Any]:
    manifest_path = project_dir / "capability_manifest.json"
    result = capability_manifest_check.check(manifest_path, project_dir=project_dir)
    manifest = read_json(manifest_path)
    tools = manifest.get("tool_detection", {}) if isinstance(manifest.get("tool_detection"), dict) else {}
    capabilities = manifest.get("capabilities", {}) if isinstance(manifest.get("capabilities"), dict) else {}
    transcription = capabilities.get("transcription", {}) if isinstance(capabilities.get("transcription"), dict) else {}
    asr = capabilities.get("asr", {}) if isinstance(capabilities.get("asr"), dict) else {}
    asr_quality = capabilities.get("asr_quality", {}) if isinstance(capabilities.get("asr_quality"), dict) else {}
    promotion = capabilities.get("commercial_promotion", {}) if isinstance(capabilities.get("commercial_promotion"), dict) else {}
    reliability = capabilities.get("production_reliability", {}) if isinstance(capabilities.get("production_reliability"), dict) else {}
    ready = capabilities.get("commercial_ready_gate", {}) if isinstance(capabilities.get("commercial_ready_gate"), dict) else {}
    user_media = capabilities.get("user_media_input", {}) if isinstance(capabilities.get("user_media_input"), dict) else {}
    media_decode = capabilities.get("media_decode", {}) if isinstance(capabilities.get("media_decode"), dict) else {}
    return {
        "status": result.get("status"),
        "manifest_path": str(manifest_path) if manifest_path.exists() else "",
        "selected_adapter": manifest.get("selected_adapter", result.get("selected_adapter", "")),
        "python_wave_verified": capabilities.get("media_metadata", {}).get("status") in {"python_wave_verified", "ffprobe_verified"} if isinstance(capabilities.get("media_metadata"), dict) else False,
        "transcription_status": transcription.get("status", ""),
        "transcription_output_artifact": transcription.get("output_artifact", ""),
        "transcription_commercial_ready": transcription.get("commercial_ready"),
        "asr_status": asr.get("status", "no_asr_configured"),
        "asr_adapter_kind": asr.get("adapter_kind", "none"),
        "asr_evidence_tier": asr.get("evidence_tier", "none"),
        "asr_output_artifact": asr.get("output_path", ""),
        "asr_quality_report_path": asr.get("quality_report_path", ""),
        "asr_quality_status": asr_quality.get("asr_quality_status", ""),
        "asr_quality_sample_count": asr_quality.get("sample_count", 0),
        "asr_quality_successful_samples": asr_quality.get("successful_samples", 0),
        "asr_quality_failed_samples": asr_quality.get("failed_samples", 0),
        "asr_quality_timeout_samples": asr_quality.get("timeout_samples", 0),
        "asr_quality_invalid_output_samples": asr_quality.get("invalid_output_samples", 0),
        "asr_quality_success_rate": asr_quality.get("success_rate", 0.0),
        "asr_quality_non_empty_text_rate": asr_quality.get("non_empty_text_rate", 0.0),
        "asr_quality_non_empty_segments_rate": asr_quality.get("non_empty_segments_rate", 0.0),
        "asr_production_candidate": asr_quality.get("production_candidate", False),
        "asr_production_verified": asr_quality.get("production_verified", False),
        "asr_production_readiness_blockers": asr_quality.get("production_readiness_blockers", []),
        "commercial_promotion_decision": promotion.get("promotion_decision", "COMMERCIAL_BETA"),
        "commercial_readiness_level": promotion.get("readiness_level", "COMMERCIAL_BETA"),
        "commercial_promotion_report_path": promotion.get("report_path", ""),
        "commercial_promotion_blockers": promotion.get("promotion_blockers", []),
        "production_reliability_status": reliability.get("status", "not_ready"),
        "production_reliability_run_count": reliability.get("run_count", 0),
        "production_reliability_report_path": reliability.get("report_path", ""),
        "commercial_ready_decision": ready.get("ready_decision", "NOT_READY"),
        "commercial_ready_report_path": ready.get("report_path", ""),
        "commercial_ready_blockers": ready.get("critical_blockers", []),
        "asr_schema_valid": asr.get("schema_valid"),
        "asr_production_asr": asr.get("production_asr"),
        "asr_degraded": asr.get("degraded"),
        "asr_returncode": asr.get("returncode"),
        "asr_timed_out": asr.get("timed_out"),
        "user_media_input_status": user_media.get("status", "not_configured"),
        "user_media_input_path": user_media.get("safe_input_path", ""),
        "user_media_input_size": user_media.get("size", 0),
        "user_media_input_sha256": user_media.get("sha256", ""),
        "user_media_metadata_status": user_media.get("metadata_status", ""),
        "user_media_adapter_status": user_media.get("adapter_status", ""),
        "user_media_manifest": user_media.get("media_manifest", ""),
        "media_decode_status": media_decode.get("status", "not_attempted"),
        "media_decode_tool": media_decode.get("tool", "none"),
        "media_decode_artifact_path": media_decode.get("artifact_path", ""),
        "media_decode_output_path": media_decode.get("output_path", ""),
        "media_decode_sha256": media_decode.get("sha256", ""),
        "media_decode_size": media_decode.get("size", 0),
        "media_decode_returncode": media_decode.get("returncode"),
        "media_decode_timed_out": media_decode.get("timed_out"),
        "ffprobe_status": tools.get("ffprobe", {}).get("status", "local_tool_unavailable") if isinstance(tools.get("ffprobe"), dict) else "local_tool_unavailable",
        "ffmpeg_status": tools.get("ffmpeg", {}).get("status", "local_tool_unavailable") if isinstance(tools.get("ffmpeg"), dict) else "local_tool_unavailable",
        "commercial_ready": manifest.get("commercial_ready"),
        "blockers": result.get("blockers", []),
    }


def score_trial(
    *,
    requirement: dict[str, Any],
    layered: dict[str, Any],
    artifact_integrity: dict[str, Any],
    reference_alignment: dict[str, Any],
    commercial: dict[str, Any],
    leak_scan: dict[str, Any],
) -> dict[str, Any]:
    parts = {
        "requirement_decision_quality": 15 if requirement.get("status") == "PASS" else 0,
        "selected_requirement_fit": 10 if read_json(pathlib.Path(requirement["paths"]["selected_requirement"])).get("selected_requirement_id") else 0,
        "product_contract_completeness": 15 if layered.get("product_contract_status") == "PASS" else 0,
        "implementation_structure_completeness": 15 if layered.get("implementation_status") == "PASS" else 0,
        "workflow_depth_and_artifact_traceability": 15 if artifact_integrity.get("stage_artifact_schema", {}).get("status") == "PASS" else 0,
        "delivery_evidence_integrity": 15 if layered.get("delivery_status") == "PASS" and artifact_integrity.get("status") == "PASS" else 0,
        "reference_profile_alignment": round(10 * int(reference_alignment.get("score", 0)) / 100),
        "commercial_readiness_honesty": 5 if commercial.get("honesty_status") == "PASS" else 0,
    }
    total = sum(parts.values())
    if leak_scan.get("status") != "PASS":
        total = 0
    if total >= 90:
        verdict = "PASS"
    elif total >= 75:
        verdict = "PARTIAL"
    elif total >= 55:
        verdict = "NEEDS_REWORK"
    else:
        verdict = "FAIL"
    return {"total": total, "verdict": verdict, "parts": parts}


def markdown_summary(result: dict[str, Any]) -> str:
    selected = result.get("selected_requirement", {})
    delivery = result.get("delivery", {})
    smoke = delivery.get("smoke_command", {})
    return "\n".join(
        [
            "# Reference Answer Project Trial Summary",
            "",
            f"- generated project path: `{result.get('generated_project_path')}`",
            f"- run_dir: `{result.get('run_dir')}`",
            f"- selected_requirement: `{selected.get('selected_requirement_name', '')}`",
            f"- layered status: `{result.get('layered_status', {}).get('overall_status')}`",
            f"- score: `{result.get('score', {}).get('total')}`",
            f"- verdict: `{result.get('score', {}).get('verdict')}`",
            f"- screenshot path: `{result.get('artifact_integrity', {}).get('screenshot_path')}`",
            f"- zip path: `{result.get('artifact_integrity', {}).get('zip_path')}`",
            f"- zip size: `{result.get('artifact_integrity', {}).get('zip_size')}`",
            f"- delivery_manifest path: `{result.get('artifact_integrity', {}).get('delivery_manifest_path')}`",
            f"- smoke command: `{' '.join(str(item) for item in smoke.get('argv', []))}`",
            f"- smoke result: `{smoke.get('status')}` returncode `{smoke.get('returncode')}`",
            f"- artifact integrity result: `{result.get('artifact_integrity', {}).get('status')}`",
            f"- fixture processing result: `{result.get('fixture_processing', {}).get('status')}`",
            f"- capability manifest result: `{result.get('capability_manifest', {}).get('status')}` selected_adapter `{result.get('capability_manifest', {}).get('selected_adapter')}`",
            f"- user media input status: `{result.get('capability_manifest', {}).get('user_media_input_status')}` path `{result.get('capability_manifest', {}).get('user_media_input_path')}`",
            f"- user media metadata status: `{result.get('capability_manifest', {}).get('user_media_metadata_status')}` adapter `{result.get('capability_manifest', {}).get('user_media_adapter_status')}`",
            f"- media decode status: `{result.get('capability_manifest', {}).get('media_decode_status')}` output `{result.get('capability_manifest', {}).get('media_decode_output_path')}`",
            f"- ASR status: `{result.get('capability_manifest', {}).get('asr_status')}` adapter `{result.get('capability_manifest', {}).get('asr_adapter_kind')}` tier `{result.get('capability_manifest', {}).get('asr_evidence_tier')}` output `{result.get('capability_manifest', {}).get('asr_output_artifact')}`",
            f"- ASR quality status: `{result.get('capability_manifest', {}).get('asr_quality_status')}` samples `{result.get('capability_manifest', {}).get('asr_quality_sample_count')}` successful `{result.get('capability_manifest', {}).get('asr_quality_successful_samples')}` failed `{result.get('capability_manifest', {}).get('asr_quality_failed_samples')}` report `{result.get('capability_manifest', {}).get('asr_quality_report_path')}`",
            f"- ASR quality rates: success `{result.get('capability_manifest', {}).get('asr_quality_success_rate')}` text `{result.get('capability_manifest', {}).get('asr_quality_non_empty_text_rate')}` segments `{result.get('capability_manifest', {}).get('asr_quality_non_empty_segments_rate')}` candidate `{result.get('capability_manifest', {}).get('asr_production_candidate')}` verified `{result.get('capability_manifest', {}).get('asr_production_verified')}`",
            f"- commercial promotion: `{result.get('capability_manifest', {}).get('commercial_promotion_decision')}` report `{result.get('capability_manifest', {}).get('commercial_promotion_report_path')}` blockers `{result.get('capability_manifest', {}).get('commercial_promotion_blockers')}`",
            f"- production reliability: `{result.get('capability_manifest', {}).get('production_reliability_status')}` runs `{result.get('capability_manifest', {}).get('production_reliability_run_count')}` report `{result.get('capability_manifest', {}).get('production_reliability_report_path')}`",
            f"- commercial ready gate: `{result.get('capability_manifest', {}).get('commercial_ready_decision')}` report `{result.get('capability_manifest', {}).get('commercial_ready_report_path')}` blockers `{result.get('capability_manifest', {}).get('commercial_ready_blockers')}`",
            f"- transcription status: `{result.get('capability_manifest', {}).get('transcription_status')}` output `{result.get('capability_manifest', {}).get('transcription_output_artifact')}`",
            f"- commercial readiness result: `{result.get('commercial_readiness', {}).get('status')}`",
            f"- reference profile alignment result: `{result.get('reference_profile_alignment', {}).get('status')}` score `{result.get('reference_profile_alignment', {}).get('score')}`",
            "",
            "## Known Gaps",
            *[f"- {gap}" for gap in result.get("known_gaps", [])],
            "",
            "## Next Recommended Action",
            result.get("next_recommended_action", ""),
        ]
    ) + "\n"


def write_gap_files(result: dict[str, Any], root: pathlib.Path) -> None:
    gaps = result.get("known_gaps", [])
    gap_lines = ["# Reference Answer Gap Analysis", ""]
    if gaps:
        gap_lines.extend(f"- {gap}" for gap in gaps)
    else:
        gap_lines.append("- No blocking trial gaps found. Commercial readiness remains beta because degraded mode is honestly declared.")
    (root / "artifacts" / "reference_answer_gap_analysis.md").write_text("\n".join(gap_lines) + "\n", encoding="utf-8")

    repair_lines = [
        "# Reference Answer Repair Plan",
        "",
        "1. Keep the generated project on the local-first shared GUI/CLI pipeline route.",
        "2. Keep User Media Pipeline Contract v1 as bounded local input evidence, not production media processing.",
        "3. Re-run the reference answer project trial after any generation or delivery evidence change.",
        "4. Supply representative real-ASR repeat runs and approved human review evidence before evaluating COMMERCIAL_READY.",
    ]
    if gaps:
        repair_lines.extend(f"- Repair: {gap}" for gap in gaps)
    (root / "artifacts" / "reference_answer_repair_plan.md").write_text("\n".join(repair_lines) + "\n", encoding="utf-8")

    leak = result.get("name_leak_scan", {})
    leak_lines = [
        "# Reference Name Leak Report",
        "",
        f"- status: `{leak.get('status')}`",
        f"- forbidden reference token count: `{leak.get('forbidden_reference_token_count')}`",
        f"- scanned file count: `{leak.get('scanned_file_count')}`",
        "- token values are redacted; report records only labels and hashes.",
        "",
    ]
    findings = leak.get("findings", [])
    if findings:
        leak_lines.append("## Findings")
        for item in findings:
            leak_lines.append(f"- `{item.get('path')}` contains `{item.get('token_label')}` hash `{item.get('token_hash')}`")
    else:
        leak_lines.append("No generated-output leaks found.")
    (root / "artifacts" / "reference_name_leak_report.md").write_text("\n".join(leak_lines) + "\n", encoding="utf-8")


def update_current_gaps(result: dict[str, Any], root: pathlib.Path) -> None:
    gaps = result.get("known_gaps", [])
    lines = [
        "# Continuous Generation Current Gaps",
        "",
        "- highest_priority_gap: `representative_real_asr_reliability_and_approved_human_review_evidence_missing`",
        f"- latest_reference_trial_verdict: `{result.get('score', {}).get('verdict')}`",
        f"- latest_reference_trial_score: `{result.get('score', {}).get('total')}`",
        f"- commercial_readiness: `{result.get('commercial_readiness', {}).get('status')}`",
        f"- user_media_input_status: `{result.get('capability_manifest', {}).get('user_media_input_status')}`",
        f"- media_decode_status: `{result.get('capability_manifest', {}).get('media_decode_status')}`",
        f"- asr_status: `{result.get('capability_manifest', {}).get('asr_status')}`",
        f"- asr_evidence_tier: `{result.get('capability_manifest', {}).get('asr_evidence_tier')}`",
        f"- asr_quality_status: `{result.get('capability_manifest', {}).get('asr_quality_status')}`",
        f"- asr_quality_sample_count: `{result.get('capability_manifest', {}).get('asr_quality_sample_count')}`",
        f"- commercial_promotion_decision: `{result.get('capability_manifest', {}).get('commercial_promotion_decision')}`",
        f"- commercial_promotion_report: `{result.get('capability_manifest', {}).get('commercial_promotion_report_path')}`",
        f"- production_reliability_status: `{result.get('capability_manifest', {}).get('production_reliability_status')}`",
        f"- commercial_ready_decision: `{result.get('capability_manifest', {}).get('commercial_ready_decision')}`",
        f"- commercial_ready_report: `{result.get('capability_manifest', {}).get('commercial_ready_report_path')}`",
        f"- full_pytest_required: `yes`",
        "",
        "## Known Gaps",
    ]
    lines.extend(f"- {gap}" for gap in gaps)
    if not gaps:
        lines.append("- No blocking trial gap. Commercial hardening remains the next step before claiming production readiness.")
    (root / "artifacts" / "continuous_generation_current_gaps.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_trial(
    *,
    reference_answer: str,
    root: pathlib.Path = ROOT,
    no_live: bool = True,
    capture_screenshot: bool = True,
    forbidden_terms: list[str] | None = None,
    use_local_transcription_fixture: bool = False,
    use_user_media_fixture: bool = False,
    use_media_decode_smoke: bool = False,
    use_real_asr_contract_fixture: bool = False,
    use_asr_quality_gate_fixture: bool = False,
    use_real_asr_multi_sample_eval_fixture: bool = False,
    use_real_asr_multi_sample_eval: bool = False,
    use_commercial_promotion_gate_fixture: bool = False,
    use_real_asr_commercial_candidate_eval: bool = False,
    use_commercial_ready_gate_fixture: bool = False,
) -> dict[str, Any]:
    root = pathlib.Path(root)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    run_dir = create_unique_run_dir(artifacts)
    project_dir = run_dir / "generated_project" / "local_media_operations_workspace"
    project_dir.mkdir(parents=True, exist_ok=True)

    detected_forbidden = detect_reference_names(reference_answer, forbidden_terms)
    profile = extract_reference_profile(reference_answer, detected_forbidden)
    write_json(run_dir / "reference_profile.redacted.json", profile)

    requirement = requirement_decision_lane.run_requirement_decision(
        NEW_CUSTOMER_GOAL,
        run_dir,
        context={"reference_complexity_target": profile["complexity_level"]},
    )
    discovery = discovery_selection_lane.run_discovery_selection(NEW_CUSTOMER_GOAL, run_dir / "discovery", candidate_count=5)
    planning = planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    implementation = implementation_structure_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    previous_transcribe_cmd = os.environ.get("CGKN_LOCAL_TRANSCRIBE_CMD")
    previous_real_asr_cmd = os.environ.get("CGKN_REAL_ASR_CMD")
    previous_asr_quality_gate = os.environ.get("CGKN_ASR_QUALITY_GATE")
    previous_asr_quality_gate_samples = os.environ.get("CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT")
    previous_asr_adapter_kind = os.environ.get("CGKN_REAL_ASR_ADAPTER_KIND")
    previous_multi_sample_eval = os.environ.get("CGKN_REAL_ASR_MULTI_SAMPLE_EVAL")
    previous_promotion_gate = os.environ.get("CGKN_COMMERCIAL_PROMOTION_GATE")
    previous_ready_gate = os.environ.get("CGKN_COMMERCIAL_READY_GATE")
    if use_local_transcription_fixture:
        fixture_adapter = project_dir / "local_transcription_fixture_adapter.py"
        os.environ["CGKN_LOCAL_TRANSCRIBE_CMD"] = f'"{sys.executable}" "{fixture_adapter}" --input "{{input}}" --output "{{output}}"'
    if use_real_asr_contract_fixture:
        asr_adapter = project_dir / "real_asr_adapter_contract.py"
        os.environ["CGKN_REAL_ASR_CMD"] = f'"{sys.executable}" "{asr_adapter}" --fixture-adapter --input "{{input}}" --output "{{output}}"'
    if use_asr_quality_gate_fixture:
        os.environ["CGKN_ASR_QUALITY_GATE"] = "1"
        os.environ["CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT"] = "3"
    if use_real_asr_multi_sample_eval_fixture:
        asr_adapter = project_dir / "real_asr_adapter_contract.py"
        os.environ["CGKN_REAL_ASR_CMD"] = f'"{sys.executable}" "{asr_adapter}" --fixture-adapter --input "{{input}}" --output "{{output}}"'
        os.environ["CGKN_REAL_ASR_ADAPTER_KIND"] = "fixture"
        os.environ["CGKN_REAL_ASR_MULTI_SAMPLE_EVAL"] = "1"
        os.environ["CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT"] = "3"
    elif use_real_asr_multi_sample_eval:
        os.environ["CGKN_REAL_ASR_ADAPTER_KIND"] = "real_local_asr"
        os.environ["CGKN_REAL_ASR_MULTI_SAMPLE_EVAL"] = "1"
        os.environ["CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT"] = "3"
    if use_commercial_promotion_gate_fixture:
        os.environ["CGKN_COMMERCIAL_PROMOTION_GATE"] = "1"
    if use_real_asr_commercial_candidate_eval:
        os.environ["CGKN_COMMERCIAL_PROMOTION_GATE"] = "1"
        os.environ["CGKN_REAL_ASR_ADAPTER_KIND"] = "real_local_asr"
        os.environ["CGKN_REAL_ASR_MULTI_SAMPLE_EVAL"] = "1"
        os.environ["CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT"] = "3"
    if use_commercial_ready_gate_fixture:
        os.environ["CGKN_COMMERCIAL_READY_GATE"] = "1"
    smoke_command = None
    if use_media_decode_smoke:
        use_user_media_fixture = True
    if use_user_media_fixture:
        smoke_command = [sys.executable, "cli.py", "--input", "fixtures/sample_audio.wav", "--output-dir", "."]
    try:
        delivery = delivery_evidence_builder.build(
            project_dir=project_dir,
            run_dir=run_dir,
            smoke_command=smoke_command,
            capture_screenshot=capture_screenshot,
        )
    finally:
        if use_local_transcription_fixture:
            if previous_transcribe_cmd is None:
                os.environ.pop("CGKN_LOCAL_TRANSCRIBE_CMD", None)
            else:
                os.environ["CGKN_LOCAL_TRANSCRIBE_CMD"] = previous_transcribe_cmd
        if use_real_asr_contract_fixture:
            if previous_real_asr_cmd is None:
                os.environ.pop("CGKN_REAL_ASR_CMD", None)
            else:
                os.environ["CGKN_REAL_ASR_CMD"] = previous_real_asr_cmd
        if use_asr_quality_gate_fixture:
            if previous_asr_quality_gate is None:
                os.environ.pop("CGKN_ASR_QUALITY_GATE", None)
            else:
                os.environ["CGKN_ASR_QUALITY_GATE"] = previous_asr_quality_gate
            if previous_asr_quality_gate_samples is None:
                os.environ.pop("CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT", None)
            else:
                os.environ["CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT"] = previous_asr_quality_gate_samples
        if use_real_asr_multi_sample_eval_fixture or use_real_asr_multi_sample_eval:
            if previous_asr_adapter_kind is None:
                os.environ.pop("CGKN_REAL_ASR_ADAPTER_KIND", None)
            else:
                os.environ["CGKN_REAL_ASR_ADAPTER_KIND"] = previous_asr_adapter_kind
            if previous_multi_sample_eval is None:
                os.environ.pop("CGKN_REAL_ASR_MULTI_SAMPLE_EVAL", None)
            else:
                os.environ["CGKN_REAL_ASR_MULTI_SAMPLE_EVAL"] = previous_multi_sample_eval
            if previous_asr_quality_gate_samples is None:
                os.environ.pop("CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT", None)
            else:
                os.environ["CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT"] = previous_asr_quality_gate_samples
            if use_real_asr_multi_sample_eval_fixture:
                if previous_real_asr_cmd is None:
                    os.environ.pop("CGKN_REAL_ASR_CMD", None)
                else:
                    os.environ["CGKN_REAL_ASR_CMD"] = previous_real_asr_cmd
        if use_commercial_promotion_gate_fixture or use_real_asr_commercial_candidate_eval:
            if previous_promotion_gate is None:
                os.environ.pop("CGKN_COMMERCIAL_PROMOTION_GATE", None)
            else:
                os.environ["CGKN_COMMERCIAL_PROMOTION_GATE"] = previous_promotion_gate
        if use_real_asr_commercial_candidate_eval and not (use_real_asr_multi_sample_eval_fixture or use_real_asr_multi_sample_eval):
            if previous_asr_adapter_kind is None:
                os.environ.pop("CGKN_REAL_ASR_ADAPTER_KIND", None)
            else:
                os.environ["CGKN_REAL_ASR_ADAPTER_KIND"] = previous_asr_adapter_kind
            if previous_multi_sample_eval is None:
                os.environ.pop("CGKN_REAL_ASR_MULTI_SAMPLE_EVAL", None)
            else:
                os.environ["CGKN_REAL_ASR_MULTI_SAMPLE_EVAL"] = previous_multi_sample_eval
            if previous_asr_quality_gate_samples is None:
                os.environ.pop("CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT", None)
            else:
                os.environ["CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT"] = previous_asr_quality_gate_samples
        if use_commercial_ready_gate_fixture:
            if previous_ready_gate is None:
                os.environ.pop("CGKN_COMMERCIAL_READY_GATE", None)
            else:
                os.environ["CGKN_COMMERCIAL_READY_GATE"] = previous_ready_gate
    layered = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir, discovery_dir=run_dir / "discovery")
    product = product_acceptance.evaluate_product_acceptance(
        project_dir,
        goal=NEW_CUSTOMER_GOAL,
        run_dir=run_dir,
        discovery_dir=run_dir / "discovery",
        require_complexity_contract=True,
    )
    artifact_integrity = evaluate_artifact_integrity(project_dir, run_dir)
    commercial = evaluate_commercial_honesty(project_dir)
    fixture_processing = evaluate_fixture_processing(project_dir)
    capability = evaluate_capability_manifest(project_dir)
    alignment = evaluate_reference_alignment(project_dir, run_dir, layered, artifact_integrity)

    leak_scan = scan_name_leaks(
        [
            project_dir,
            run_dir / "requirement_decision",
            run_dir / "discovery",
            run_dir / "reference_profile.redacted.json",
        ],
        detected_forbidden,
    )
    score = score_trial(
        requirement=requirement,
        layered=layered,
        artifact_integrity=artifact_integrity,
        reference_alignment=alignment,
        commercial=commercial,
        leak_scan=leak_scan,
    )

    known_gaps: list[str] = []
    known_gaps.extend(str(item) for item in layered.get("known_gaps", []) if str(item).strip())
    known_gaps.extend(str(item) for item in artifact_integrity.get("blockers", []) if str(item).strip())
    known_gaps.extend(f"fixture_processing:{item}" for item in fixture_processing.get("blockers", []))
    known_gaps.extend(f"capability_manifest:{item}" for item in capability.get("blockers", []))
    known_gaps.extend(f"reference_alignment:{item}" for item in alignment.get("missing", []))
    if commercial.get("status") != "COMMERCIAL_READY":
        known_gaps.append("commercial_readiness:user_media_contract_not_production_media_or_asr")
    known_gaps.extend(f"commercial_promotion:{item}" for item in commercial.get("promotion_blockers", []) if str(item).strip())
    known_gaps.extend(f"commercial_ready:{item}" for item in commercial.get("ready_blockers", []) if str(item).strip())
    if capability.get("selected_adapter") == "python_wave_verified":
        known_gaps.append("fixture_coverage:bounded_python_wave_only_no_real_media_decode_or_model_adapter")
    if capability.get("user_media_input_status") == "verified":
        known_gaps.append("user_media_pipeline:real_input_contract_verified_not_production_media_pipeline")
    else:
        known_gaps.append("user_media_pipeline:real_input_contract_not_exercised")
    if capability.get("media_decode_status") == "verified":
        known_gaps.append("media_decode:bounded_ffmpeg_extract_verified_not_production_pipeline")
    elif capability.get("media_decode_status") == "unavailable":
        known_gaps.append("media_decode:ffmpeg_unavailable")
    elif capability.get("media_decode_status") == "failed":
        known_gaps.append("media_decode:bounded_extract_failed")
    else:
        known_gaps.append("media_decode:not_attempted")
    transcription_status = str(capability.get("transcription_status", ""))
    if transcription_status in {"placeholder_transcription", "local_model_unavailable"}:
        known_gaps.append("local_model_adapter:no_real_model_configured_for_reference_trial")
    elif transcription_status == "local_model_verified":
        known_gaps.append("local_model_adapter:command_fixture_verified_not_production_asr")
    asr_status = str(capability.get("asr_status", ""))
    asr_tier = str(capability.get("asr_evidence_tier", "none"))
    if asr_status == "asr_contract_fixture_verified" or asr_tier == "contract_fixture":
        known_gaps.append("asr:contract_fixture_verified_not_production_asr")
    elif asr_status == "real_local_asr_verified":
        known_gaps.append("asr:single_sample_real_asr_not_commercial_ready")
    elif asr_status == "command_fixture_transcription":
        known_gaps.append("asr:command_fixture_transcription_not_real_asr")
    elif asr_status == "placeholder_transcription":
        known_gaps.append("asr:placeholder_transcription_not_real_asr")
    else:
        known_gaps.append(f"asr:{asr_status or 'no_asr_configured'}")
    if not no_live:
        known_gaps.append("provider_transport:live_provider_not_invoked_by_trial_runner")
    if leak_scan.get("status") != "PASS":
        known_gaps.append("reference_name_leak_detected")
    known_gaps = sorted(dict.fromkeys(known_gaps))

    selected = read_json(pathlib.Path(requirement["paths"]["selected_requirement"]))
    result = {
        "created_at": now(),
        "mode": "no_live" if no_live else "live_requested_not_supported",
        "use_local_transcription_fixture": use_local_transcription_fixture,
        "use_user_media_fixture": use_user_media_fixture,
        "use_media_decode_smoke": use_media_decode_smoke,
        "use_real_asr_contract_fixture": use_real_asr_contract_fixture,
        "use_asr_quality_gate_fixture": use_asr_quality_gate_fixture,
        "use_real_asr_multi_sample_eval_fixture": use_real_asr_multi_sample_eval_fixture,
        "use_real_asr_multi_sample_eval": use_real_asr_multi_sample_eval,
        "use_commercial_promotion_gate_fixture": use_commercial_promotion_gate_fixture,
        "use_real_asr_commercial_candidate_eval": use_real_asr_commercial_candidate_eval,
        "use_commercial_ready_gate_fixture": use_commercial_ready_gate_fixture,
        "reference_profile": profile,
        "generated_project_path": str(project_dir),
        "run_dir": str(run_dir),
        "selected_requirement": selected,
        "requirement_decision": {"status": requirement.get("status"), "paths": requirement.get("paths", {})},
        "discovery_selection": {"status": discovery.get("status"), "paths": discovery.get("paths", {})},
        "planning_materialization": planning,
        "implementation_materialization": implementation,
        "delivery": delivery,
        "layered_status": {
            "requirement_decision_status": layered.get("requirement_decision_status"),
            "product_contract_status": layered.get("product_contract_status"),
            "implementation_status": layered.get("implementation_status"),
            "delivery_status": layered.get("delivery_status"),
            "artifact_integrity_status": artifact_integrity.get("status"),
            "commercial_readiness_status": commercial.get("status"),
            "reference_profile_alignment_status": alignment.get("status"),
            "overall_status": layered.get("overall_status"),
        },
        "product_acceptance": product,
        "artifact_integrity": artifact_integrity,
        "fixture_processing": fixture_processing,
        "capability_manifest": capability,
        "commercial_readiness": commercial,
        "reference_profile_alignment": alignment,
        "name_leak_scan": leak_scan,
        "score": score,
        "known_gaps": known_gaps,
        "next_recommended_action": "Collect representative real-local-ASR repeat runs and approved human review evidence, then rerun the independent COMMERCIAL_READY gate.",
    }

    write_json(artifacts / "reference_answer_trial.json", result)
    (artifacts / "reference_answer_trial_summary.md").write_text(markdown_summary(result), encoding="utf-8")
    write_gap_files(result, root)
    update_current_gaps(result, root)
    continuous_generation_ledger.append_iteration(
        {
            "selected_gap": "reference_answer_project_generation_validation",
            "layer": "delivery",
            "reason_for_priority": "Validate CGKN can convert a reference-grade answer into a new neutral generated project without leaking old identifiers.",
            "micro_plan": [
                "extract redacted reference profile",
                "run no-live requirement/discovery/materialization/delivery flow",
                "score layered evidence and reference alignment",
                "scan generated outputs for reference-token leaks",
            ],
            "acceptance_criteria": [
                "new project is not named after the reference",
                "requirement decision artifacts exist",
                "product contract docs exist",
                "implementation has shared GUI/CLI pipeline core",
                "delivery requires screenshot and zip evidence",
                "commercial readiness is not inferred from delivery PASS",
            ],
            "files_changed": [
                "scripts/run_reference_answer_project_trial.py",
                "tests/test_reference_answer_project_trial.py",
                "artifacts/reference_answer_trial_summary.md",
                "artifacts/reference_answer_trial.json",
                "artifacts/reference_answer_gap_analysis.md",
                "artifacts/reference_answer_repair_plan.md",
                "artifacts/reference_name_leak_report.md",
                "artifacts/continuous_generation_current_gaps.md",
            ],
            "tests_added_or_updated": ["tests/test_reference_answer_project_trial.py"],
            "commands_run": ["python scripts/run_reference_answer_project_trial.py --no-live"],
            "test_results": [{"name": "reference_answer_project_trial", "status": score["verdict"]}],
            "benchmark_results": [{"name": "reference_profile_alignment", "status": alignment["status"], "score": alignment["score"]}],
            "known_gaps_after_iteration": known_gaps,
            "next_recommended_action": result["next_recommended_action"],
            "status": "PASS" if score["verdict"] in {"PASS", "PARTIAL"} and leak_scan.get("status") == "PASS" else "FAIL",
        },
        root / "artifacts" / "continuous_generation_iterations.jsonl",
    )
    return result


def load_reference_answer(args: argparse.Namespace) -> str:
    if args.reference_answer:
        return str(args.reference_answer)
    if args.reference_answer_file:
        return pathlib.Path(args.reference_answer_file).read_text(encoding="utf-8", errors="replace")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-answer-file", default="")
    parser.add_argument("--reference-answer", default="")
    parser.add_argument("--forbidden-name", action="append", default=[])
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("--use-local-transcription-fixture", action="store_true")
    parser.add_argument("--use-user-media-fixture", action="store_true")
    parser.add_argument("--use-media-decode-smoke", action="store_true")
    parser.add_argument("--use-real-asr-contract-fixture", action="store_true")
    parser.add_argument("--use-asr-quality-gate-fixture", action="store_true")
    parser.add_argument("--use-real-asr-multi-sample-eval-fixture", action="store_true")
    parser.add_argument("--use-real-asr-multi-sample-eval", action="store_true")
    parser.add_argument("--use-commercial-promotion-gate-fixture", action="store_true")
    parser.add_argument("--use-real-asr-commercial-candidate-eval", action="store_true")
    parser.add_argument("--use-commercial-ready-gate-fixture", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    reference_answer = load_reference_answer(args)
    if not reference_answer.strip():
        reference_answer = "Reference answer described a local-first production-scale project with GUI, CLI, pipeline, artifacts, delivery evidence, and layered acceptance."
    result = run_trial(
        reference_answer=reference_answer,
        root=ROOT,
        no_live=not args.live,
        capture_screenshot=not args.no_screenshot,
        forbidden_terms=list(args.forbidden_name or []),
        use_local_transcription_fixture=bool(args.use_local_transcription_fixture),
        use_user_media_fixture=bool(args.use_user_media_fixture),
        use_media_decode_smoke=bool(args.use_media_decode_smoke),
        use_real_asr_contract_fixture=bool(args.use_real_asr_contract_fixture),
        use_asr_quality_gate_fixture=bool(args.use_asr_quality_gate_fixture),
        use_real_asr_multi_sample_eval_fixture=bool(args.use_real_asr_multi_sample_eval_fixture),
        use_real_asr_multi_sample_eval=bool(args.use_real_asr_multi_sample_eval),
        use_commercial_promotion_gate_fixture=bool(args.use_commercial_promotion_gate_fixture),
        use_real_asr_commercial_candidate_eval=bool(args.use_real_asr_commercial_candidate_eval),
        use_commercial_ready_gate_fixture=bool(args.use_commercial_ready_gate_fixture),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"REFERENCE_ANSWER_PROJECT_TRIAL: {result['score']['verdict']}")
        print(f"score={result['score']['total']}")
        print(f"project_dir={result['generated_project_path']}")
        print(f"run_dir={result['run_dir']}")
        print(f"summary={ROOT / 'artifacts' / 'reference_answer_trial_summary.md'}")
    return 0 if result["score"]["verdict"] in {"PASS", "PARTIAL"} and result["name_leak_scan"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
