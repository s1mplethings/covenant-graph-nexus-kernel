#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


RISK_VALUES = {"low", "medium", "high"}

NUMERIC_DIMENSIONS = [
    "complexity_score",
    "local_first_feasibility",
    "pipeline_clarity",
    "artifact_potential",
    "gui_cli_suitability",
    "delivery_feasibility",
    "testability_score",
    "screenshot_feasibility",
]

SCORING_DIMENSIONS = NUMERIC_DIMENSIONS + [
    "external_dependency_risk",
    "demo_degradation_risk",
    "fake_pass_risk",
]

DEFAULT_REQUIRED_ARTIFACT_FIELDS = [
    "stage",
    "status",
    "count",
    "input_path",
    "output_path",
    "created_at",
    "upstream_artifacts",
    "items",
]

DEFAULT_DELIVERY_EVIDENCE = [
    "README.md",
    "TEST_REPORT.md",
    "DELIVERY_NOTES.md",
    "final_project_bundle.zip",
    "screenshot",
    "run_dir",
]

FORBIDDEN_SHORTCUTS = [
    "single_file_demo",
    "static_preview_only",
    "readme_only_delivery",
    "fake_pass",
    "gui_logic_separate_from_cli_logic",
    "artifact_name_only_without_schema",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", str(text or "").lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:72] or "complex_project"


def risk_penalty(value: str) -> int:
    return {"low": 0, "medium": 10, "high": 30}.get(str(value), 30)


def weighted_total(candidate: dict[str, Any]) -> int:
    score = (
        int(candidate.get("complexity_score", 0)) * 0.2
        + int(candidate.get("local_first_feasibility", 0)) * 0.15
        + int(candidate.get("pipeline_clarity", 0)) * 0.15
        + int(candidate.get("artifact_potential", 0)) * 0.15
        + int(candidate.get("gui_cli_suitability", 0)) * 0.12
        + int(candidate.get("delivery_feasibility", 0)) * 0.11
        + int(candidate.get("testability_score", 0)) * 0.08
        + int(candidate.get("screenshot_feasibility", 0)) * 0.04
    )
    penalty = (
        risk_penalty(str(candidate.get("external_dependency_risk", "high"))) * 0.4
        + risk_penalty(str(candidate.get("demo_degradation_risk", "high"))) * 0.35
        + risk_penalty(str(candidate.get("fake_pass_risk", "high"))) * 0.25
    )
    return max(0, min(100, round(score - penalty)))


def _video_candidate(user_goal: str) -> dict[str, Any]:
    return {
        "id": "local_video_workbench",
        "name": "Local Video Material Workbench",
        "summary": "Local-first workbench for importing media, extracting or simulating audio, segmenting transcripts, scoring clips, selecting outputs, and exporting evidence.",
        "target_user": "Editors and operators who need a repeatable local media processing workflow.",
        "core_workflow": [
            "import local video",
            "extract audio with honest degraded fallback",
            "chunk and transcribe",
            "analyze and score segments",
            "select candidate clips",
            "render/export reports and manifests",
        ],
        "likely_pages": ["Import", "Pipeline Run", "Segments", "Clip Review", "Exports", "Settings"],
        "likely_modules": ["orchestrator", "stages", "artifact_store", "cli", "gui", "degraded_runtime", "tests"],
        "pipeline_stages": [
            "ingest_video",
            "extract_audio",
            "chunk_audio",
            "transcribe_audio",
            "analyze_segments",
            "select_segments",
            "render_clips",
            "export_results",
        ],
        "expected_artifacts": [
            "stage_plan.json",
            "media_manifest.json",
            "audio_chunk_manifest.json",
            "transcript_merged.json",
            "segment_analysis.json",
            "selected_segments.json",
            "clip_manifest.json",
            "export_results.json",
        ],
        "local_first_feasibility": 86,
        "complexity_score": 88,
        "pipeline_clarity": 92,
        "artifact_potential": 94,
        "gui_cli_suitability": 89,
        "delivery_feasibility": 78,
        "testability_score": 82,
        "screenshot_feasibility": 84,
        "external_dependency_risk": "medium",
        "demo_degradation_risk": "low",
        "fake_pass_risk": "low",
        "honest_degraded_mode_available": True,
    }


def _data_ops_candidate(user_goal: str) -> dict[str, Any]:
    return {
        "id": "local_data_quality_studio",
        "name": "Local Data Quality Studio",
        "summary": "A local CSV/JSON intake, profiling, rule validation, repair suggestion, export, and audit-report product.",
        "target_user": "Operations teams cleaning files before upload into business systems.",
        "core_workflow": ["import files", "profile columns", "infer rules", "validate rows", "review fixes", "export clean data"],
        "likely_pages": ["Sources", "Profile", "Rules", "Issues", "Fix Review", "Exports"],
        "likely_modules": ["orchestrator", "stages", "rules", "artifact_store", "cli", "gui", "tests"],
        "pipeline_stages": [
            "load_sources",
            "profile_schema",
            "infer_rules",
            "validate_records",
            "cluster_issues",
            "suggest_repairs",
            "export_clean_dataset",
            "write_audit_report",
        ],
        "expected_artifacts": [
            "source_manifest.json",
            "schema_profile.json",
            "rule_catalog.json",
            "validation_report.json",
            "issue_clusters.json",
            "repair_suggestions.json",
            "export_manifest.json",
            "audit_report.json",
        ],
        "local_first_feasibility": 94,
        "complexity_score": 80,
        "pipeline_clarity": 86,
        "artifact_potential": 88,
        "gui_cli_suitability": 84,
        "delivery_feasibility": 88,
        "testability_score": 90,
        "screenshot_feasibility": 82,
        "external_dependency_risk": "low",
        "demo_degradation_risk": "medium",
        "fake_pass_risk": "low",
        "honest_degraded_mode_available": True,
    }


def _asset_pack_candidate(user_goal: str) -> dict[str, Any]:
    return {
        "id": "local_asset_pack_planner",
        "name": "Local Asset Pack Planner",
        "summary": "A structured asset intake, tagging, license check, dependency mapping, packaging, and release-note workbench.",
        "target_user": "Small product teams assembling local deliverable asset packs.",
        "core_workflow": ["import assets", "tag metadata", "check licenses", "map dependencies", "build package", "write release report"],
        "likely_pages": ["Library", "Metadata", "Dependency Map", "Validation", "Package", "Release Notes"],
        "likely_modules": ["orchestrator", "stages", "metadata", "packager", "cli", "gui", "tests"],
        "pipeline_stages": [
            "discover_assets",
            "classify_assets",
            "extract_metadata",
            "validate_license_notes",
            "map_dependencies",
            "build_release_manifest",
            "package_assets",
            "write_delivery_report",
        ],
        "expected_artifacts": [
            "asset_manifest.json",
            "classification_report.json",
            "metadata_index.json",
            "license_review.json",
            "dependency_map.json",
            "release_manifest.json",
            "package_manifest.json",
            "delivery_report.json",
        ],
        "local_first_feasibility": 90,
        "complexity_score": 76,
        "pipeline_clarity": 83,
        "artifact_potential": 84,
        "gui_cli_suitability": 80,
        "delivery_feasibility": 86,
        "testability_score": 84,
        "screenshot_feasibility": 80,
        "external_dependency_risk": "low",
        "demo_degradation_risk": "medium",
        "fake_pass_risk": "low",
        "honest_degraded_mode_available": True,
    }


def _cloud_ai_candidate(user_goal: str) -> dict[str, Any]:
    return {
        "id": "cloud_ai_autopilot_suite",
        "name": "Cloud AI Autopilot Suite",
        "summary": "A fully automated cloud AI workflow requiring live model, storage, queue, and external media services.",
        "target_user": "Teams with managed cloud AI infrastructure.",
        "core_workflow": ["connect cloud accounts", "call remote models", "store remote assets", "publish automated outputs"],
        "likely_pages": ["Cloud Accounts", "Jobs", "Remote Assets", "Model Runs"],
        "likely_modules": ["cloud_client", "remote_jobs", "billing_guard", "gui"],
        "pipeline_stages": ["authenticate_cloud", "submit_model_jobs", "poll_remote_results"],
        "expected_artifacts": ["remote_job_log.json", "cloud_result_manifest.json"],
        "local_first_feasibility": 35,
        "complexity_score": 82,
        "pipeline_clarity": 55,
        "artifact_potential": 50,
        "gui_cli_suitability": 58,
        "delivery_feasibility": 38,
        "testability_score": 42,
        "screenshot_feasibility": 64,
        "external_dependency_risk": "high",
        "demo_degradation_risk": "high",
        "fake_pass_risk": "high",
        "honest_degraded_mode_available": False,
    }


def _small_demo_candidate(user_goal: str) -> dict[str, Any]:
    return {
        "id": "single_page_status_demo",
        "name": "Single Page Status Demo",
        "summary": "A static page showing a mocked project status table.",
        "target_user": "Viewer of a simple prototype.",
        "core_workflow": ["open page", "view static cards"],
        "likely_pages": ["Home"],
        "likely_modules": ["static_page"],
        "pipeline_stages": ["render_static_preview"],
        "expected_artifacts": ["status.json"],
        "local_first_feasibility": 96,
        "complexity_score": 28,
        "pipeline_clarity": 35,
        "artifact_potential": 30,
        "gui_cli_suitability": 20,
        "delivery_feasibility": 96,
        "testability_score": 30,
        "screenshot_feasibility": 95,
        "external_dependency_risk": "low",
        "demo_degradation_risk": "high",
        "fake_pass_risk": "high",
        "honest_degraded_mode_available": True,
    }


def generate_candidates(user_goal: str, count: int = 4) -> list[dict[str, Any]]:
    lowered = user_goal.lower()
    candidates: list[dict[str, Any]] = []
    if any(token in lowered for token in ("video", "media", "clip", "audio", "transcribe", "视频", "音频", "素材")):
        candidates.append(_video_candidate(user_goal))
    candidates.extend(
        [
            _data_ops_candidate(user_goal),
            _asset_pack_candidate(user_goal),
            _cloud_ai_candidate(user_goal),
            _small_demo_candidate(user_goal),
        ]
    )
    if not any(item["id"] == "local_video_workbench" for item in candidates):
        candidates.insert(1, _video_candidate(user_goal))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate["id"] in seen:
            continue
        seen.add(candidate["id"])
        candidate = dict(candidate)
        candidate["user_goal_alignment_note"] = f"Derived from rough goal: {user_goal[:240]}"
        candidate["total_score"] = weighted_total(candidate)
        deduped.append(candidate)
    count = max(3, min(5, int(count or 4)))
    return deduped[:count]


def rejection_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if int(candidate.get("complexity_score", 0)) < 60:
        reasons.append("complexity_score_lt_60")
    if candidate.get("demo_degradation_risk") == "high":
        reasons.append("demo_degradation_risk_high")
    if candidate.get("fake_pass_risk") == "high":
        reasons.append("fake_pass_risk_high")
    if candidate.get("external_dependency_risk") == "high" and not candidate.get("honest_degraded_mode_available"):
        reasons.append("external_dependency_high_without_honest_degraded_mode")
    if not candidate.get("pipeline_stages"):
        reasons.append("pipeline_stages_missing")
    if len(candidate.get("pipeline_stages", [])) < 4:
        reasons.append("pipeline_too_short")
    if not candidate.get("expected_artifacts"):
        reasons.append("testable_artifacts_missing")
    if int(candidate.get("gui_cli_suitability", 0)) < 70:
        reasons.append("no_clear_gui_cli_shared_core_potential")
    return reasons


def selection_eligible(candidate: dict[str, Any]) -> bool:
    if rejection_reasons(candidate):
        return False
    return (
        int(candidate.get("complexity_score", 0)) >= 75
        and int(candidate.get("local_first_feasibility", 0)) >= 70
        and int(candidate.get("pipeline_clarity", 0)) >= 70
        and int(candidate.get("artifact_potential", 0)) >= 70
        and int(candidate.get("gui_cli_suitability", 0)) >= 70
        and int(candidate.get("delivery_feasibility", 0)) >= 65
        and int(candidate.get("testability_score", 0)) >= 65
    )


def build_scorecard(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    scores = []
    for candidate in candidates:
        scores.append(
            {
                "id": candidate["id"],
                "name": candidate["name"],
                "total_score": candidate["total_score"],
                "eligible": selection_eligible(candidate),
                "rejection_reasons": rejection_reasons(candidate),
                **{key: candidate.get(key) for key in SCORING_DIMENSIONS},
            }
        )
    return {"scoring_dimensions": SCORING_DIMENSIONS, "scores": scores}


def select_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [candidate for candidate in candidates if selection_eligible(candidate)]
    if not eligible:
        return None
    return sorted(eligible, key=lambda item: (int(item.get("total_score", 0)), int(item.get("complexity_score", 0))), reverse=True)[0]


def build_selected_direction(selected: dict[str, Any]) -> dict[str, Any]:
    stages = list(selected.get("pipeline_stages", []))
    artifacts = list(selected.get("expected_artifacts", []))
    return {
        "selected_id": selected["id"],
        "selected_name": selected["name"],
        "selection_reason": "Best weighted fit across complexity, local-first feasibility, pipeline clarity, artifact potential, GUI/CLI suitability, delivery feasibility, and testability.",
        "why_not_too_small": f"Requires {len(stages)} pipeline stages, {len(artifacts)} stage artifacts, planning docs, shared core, CLI, GUI, runtime evidence, screenshot, and final bundle.",
        "why_not_too_dependency_heavy": "External integrations are optional or degradable; the project can run locally with honest degraded mode.",
        "why_deliverable": "The selected shape has deterministic artifacts, local fixtures, shared core modules, and verifiable delivery evidence.",
        "required_complexity_floor": {
            "min_pages": max(4, len(selected.get("likely_pages", []))),
            "min_modules": max(6, len(selected.get("likely_modules", []))),
            "min_pipeline_stages": max(6, len(stages)),
            "min_stage_artifacts": max(6, len(artifacts)),
            "requires_gui": True,
            "requires_cli": True,
            "requires_shared_core": True,
            "requires_runtime_evidence": True,
            "requires_final_bundle": True,
            "requires_screenshot": True,
        },
    }


def build_contract(selected: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": "complexity_project_contract_v1",
        "selected_project_id": selected["id"],
        "selected_project_name": selected["name"],
        "selected_project_summary": selected["summary"],
        "required_planning_docs": [
            "product_brief.md",
            "technical_plan.md",
            "interaction_design.md",
            "acceptance_matrix.md",
        ],
        "required_core_files": [
            "orchestrator.py",
            "stages.py",
        ],
        "required_interfaces": [
            "cli",
            "gui",
        ],
        "requires_shared_gui_cli_core": True,
        "required_pipeline_stages": list(selected.get("pipeline_stages", [])),
        "required_stage_artifacts": list(selected.get("expected_artifacts", [])),
        "required_artifact_fields": DEFAULT_REQUIRED_ARTIFACT_FIELDS,
        "required_delivery_evidence": DEFAULT_DELIVERY_EVIDENCE,
        "honest_degraded_mode_required": True,
        "forbidden_shortcuts": FORBIDDEN_SHORTCUTS,
        "downstream_requirements": [
            "product_brief.md must cite complexity_project_contract.json",
            "technical_plan.md must cite complexity_project_contract.json",
            "interaction_design.md must cite complexity_project_contract.json",
            "acceptance_matrix.md must cite complexity_project_contract.json",
            "provider generation must implement the selected direction, not a generic version of the raw prompt",
        ],
    }


def rejected_options_markdown(candidates: list[dict[str, Any]], selected: dict[str, Any] | None) -> str:
    selected_id = str((selected or {}).get("id", ""))
    lines = ["# Rejected Options", ""]
    for candidate in candidates:
        if candidate["id"] == selected_id:
            continue
        reasons = rejection_reasons(candidate)
        if not reasons:
            reasons = ["lower_weighted_score_than_selected_direction"]
        lines.extend(
            [
                f"## {candidate['name']}",
                "",
                f"- id: `{candidate['id']}`",
                f"- total_score: `{candidate['total_score']}`",
                f"- rejection_reasons: {', '.join(reasons)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def discovery_brief_markdown(user_goal: str, candidates: list[dict[str, Any]], selected: dict[str, Any] | None, status: str) -> str:
    selected_text = selected["name"] if selected else "NEEDS_REWORK"
    return "\n".join(
        [
            "# Discovery Brief",
            "",
            f"- status: `{status}`",
            f"- rough_user_goal: {user_goal}",
            f"- candidate_count: `{len(candidates)}`",
            f"- selected_project_direction: `{selected_text}`",
            "",
            "Standard flow:",
            "",
            "rough_user_goal -> discovery_brief -> candidate_directions -> candidate_scorecard -> selected_project_direction -> rejected_options -> complexity_project_contract -> downstream planning / generation",
            "",
            "Discovery did not generate target project code. It only generated direction, scoring, rejection, and contract artifacts.",
        ]
    ) + "\n"


def run_discovery_selection(user_goal: str, discovery_dir: pathlib.Path, *, candidate_count: int = 4) -> dict[str, Any]:
    discovery = pathlib.Path(discovery_dir)
    candidates = generate_candidates(user_goal, candidate_count)
    selected = select_candidate(candidates)
    status = "PASS" if selected else "NEEDS_REWORK"
    scorecard = build_scorecard(candidates)
    selected_doc = build_selected_direction(selected) if selected else {
        "status": "NEEDS_REWORK",
        "selected_id": "",
        "selected_name": "",
        "selection_reason": "No candidate met the complexity, local-first, delivery, testability, and risk thresholds.",
        "rework_reasons": sorted({reason for candidate in candidates for reason in rejection_reasons(candidate)}),
    }
    contract = build_contract(selected) if selected else {
        "contract_id": "complexity_project_contract_v1",
        "status": "NEEDS_REWORK",
        "reason": "No selected direction; downstream generation must not start.",
    }
    candidate_doc = {"user_goal": user_goal, "generated_at": now(), "candidates": candidates}
    paths = {
        "discovery_brief": str(discovery / "discovery_brief.md"),
        "candidate_directions": str(discovery / "candidate_directions.json"),
        "candidate_scorecard": str(discovery / "candidate_scorecard.json"),
        "selected_project_direction": str(discovery / "selected_project_direction.json"),
        "rejected_options": str(discovery / "rejected_options.md"),
        "complexity_project_contract": str(discovery / "complexity_project_contract.json"),
    }
    write_text(pathlib.Path(paths["discovery_brief"]), discovery_brief_markdown(user_goal, candidates, selected, status))
    write_json(pathlib.Path(paths["candidate_directions"]), candidate_doc)
    write_json(pathlib.Path(paths["candidate_scorecard"]), scorecard)
    write_json(pathlib.Path(paths["selected_project_direction"]), selected_doc)
    write_text(pathlib.Path(paths["rejected_options"]), rejected_options_markdown(candidates, selected))
    write_json(pathlib.Path(paths["complexity_project_contract"]), contract)
    return {
        "status": status,
        "user_goal": user_goal,
        "candidate_count": len(candidates),
        "selected_project_direction": selected_doc,
        "complexity_project_contract": contract,
        "paths": paths,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--candidate-count", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_discovery_selection(args.goal, pathlib.Path(args.out_dir), candidate_count=args.candidate_count)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"DISCOVERY_SELECTION: {result['status']}")
        print(f"discovery_dir={pathlib.Path(args.out_dir).resolve()}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
