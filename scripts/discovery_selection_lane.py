#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

try:
    import requirement_decision_lane
except ModuleNotFoundError:  # pragma: no cover
    from scripts import requirement_decision_lane


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

DELIVERY_EVIDENCE_TERMS = (
    "截图",
    "演示视频",
    "demo video",
    "screenshot",
    "测试报告",
    "test report",
    "交付清单",
    "delivery manifest",
    "delivery_manifest",
    "final_project_bundle",
    "最终 zip",
    "public delivery gate",
)

MEDIA_PRODUCT_TERMS = (
    "视频处理",
    "视频素材",
    "视频创作者",
    "素材处理",
    "音频处理",
    "视频剪辑",
    "剪辑工作台",
    "切片工作台",
    "视频切片",
    "长视频",
    "候选片段",
    "转录",
    "video processing",
    "video workbench",
    "video slicer",
    "video clip",
    "media review",
    "media production",
    "media processing",
    "media evidence",
    "media pipeline",
    "video material",
    "transcribe",
    "clip selection",
)

VISUAL_NOVEL_PRODUCT_TERMS = (
    "视觉小说",
    "剧情树",
    "剧情分支",
    "人物立绘",
    "角色立绘",
    "vn studio",
    "visual novel",
    "story tree",
    "story graph",
    "branching narrative",
    "character sprite",
)

TASK_BOARD_PRODUCT_TERMS = ("任务看板", "个人看板", "task board", "kanban", "todo board", "待办看板")

SPECIALIZED_ANALYSIS_PRODUCT_TERMS = (
    "counter-strike",
    "counter strike",
    "cs2",
    "steam",
    "faceit",
    "demo parser",
    "demo download",
    "match demo",
    "crosshair",
    "aim analysis",
    "cheat detection",
    "anti-cheat",
    "反作弊",
    "开挂",
    "准星",
)

NEGATED_CAPABILITY_MARKERS = (
    "不需要",
    "不处理",
    "不要",
    "无需",
    "排除",
    "without ",
    "no ",
    "not ",
)


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


def product_domain_goal(user_goal: str) -> str:
    chunks = re.split(r"[\n。！？!?；;]+", str(user_goal or "").lower())
    product_chunks = [
        chunk.strip()
        for chunk in chunks
        if chunk.strip() and not any(term in chunk for term in DELIVERY_EVIDENCE_TERMS)
    ]
    return "\n".join(product_chunks) or str(user_goal or "").lower()


def goal_has_positive_term(user_goal: str, terms: tuple[str, ...]) -> bool:
    clauses = re.split(r"[\n。！？!?；;，,]+", product_domain_goal(user_goal))
    for clause in clauses:
        if not any(term in clause for term in terms):
            continue
        if any(marker in clause for marker in NEGATED_CAPABILITY_MARKERS):
            continue
        return True
    return False


def goal_has_media_product(user_goal: str) -> bool:
    return goal_has_positive_term(user_goal, MEDIA_PRODUCT_TERMS)


def goal_has_visual_novel_product(user_goal: str) -> bool:
    domain_goal = product_domain_goal(user_goal)
    return any(token in domain_goal for token in VISUAL_NOVEL_PRODUCT_TERMS) or bool(
        re.search(r"\bvn\b", domain_goal)
    )


def goal_has_task_board_product(user_goal: str) -> bool:
    return any(token in product_domain_goal(user_goal) for token in TASK_BOARD_PRODUCT_TERMS)


def goal_has_specialized_analysis_product(user_goal: str) -> bool:
    return any(token in product_domain_goal(user_goal) for token in SPECIALIZED_ANALYSIS_PRODUCT_TERMS)


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


def _goal_candidate_id(domain: str) -> str:
    return {
        "local_media_workbench": "local_video_workbench",
        "local_task_board": "local_task_board",
        "visual_novel_editor": "local_visual_novel_studio",
        "specialized_analysis_workbench": "goal_derived_specialized_analysis_workbench",
    }.get(domain, f"goal_driven_{re.sub(r'[^a-z0-9]+', '_', domain.lower()).strip('_')}")


def _goal_plan_candidate(
    user_goal: str,
    goal_spec: dict[str, Any],
    project_plan: dict[str, Any],
) -> dict[str, Any]:
    domain = str(goal_spec.get("domain", "custom_local_application"))
    workstreams = [
        row
        for row in project_plan.get("workstreams", [])
        if isinstance(row, dict) and row.get("id") not in {"foundation", "delivery"}
    ]
    stages = [str(row.get("id", "")) for row in project_plan.get("workstreams", []) if isinstance(row, dict)]
    artifacts = [str(item) for item in project_plan.get("business_outputs", [])]
    interaction_modes = requirement_decision_lane.goal_interaction_modes(goal_spec)
    names = {
        "local_media_workbench": "Local Video Workbench",
        "visual_novel_editor": "Local Visual Novel Studio",
        "local_task_board": "Local Task Board",
        "specialized_analysis_workbench": "Goal-Derived Specialized Analysis Workbench",
    }
    return {
        "id": _goal_candidate_id(domain),
        "name": names.get(domain, domain.replace("_", " ").title()),
        "summary": str(goal_spec.get("goal", user_goal)),
        "target_user": "The user described by the current goal.",
        "core_workflow": [str(item) for item in goal_spec.get("user_flows", [])],
        "likely_pages": [
            str(item)
            for item in goal_spec.get("interfaces", [])
            if str(item).strip().lower() not in {"cli", "json_report", "html_report"}
        ],
        "likely_modules": [str(row.get("id", "")) for row in workstreams],
        "pipeline_stages": stages,
        "expected_artifacts": artifacts,
        "local_first_feasibility": 96,
        "complexity_score": 88,
        "pipeline_clarity": 96,
        "artifact_potential": 94,
        "gui_cli_suitability": 90 if interaction_modes else 75,
        "delivery_feasibility": 94,
        "testability_score": 98,
        "screenshot_feasibility": 90,
        "external_dependency_risk": "low",
        "demo_degradation_risk": "low",
        "fake_pass_risk": "low",
        "honest_degraded_mode_available": True,
        "goal_spec_domain": domain,
        "canonical_goal_spec": goal_spec,
        "canonical_project_plan": project_plan,
    }


def generate_candidates(
    user_goal: str,
    count: int = 4,
    *,
    goal_spec: dict[str, Any] | None = None,
    project_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    canonical_goal_spec = goal_spec or requirement_decision_lane.build_goal_spec(user_goal)
    canonical_project_plan = project_plan or requirement_decision_lane.build_goal_project_plan(canonical_goal_spec)
    candidates: list[dict[str, Any]] = []
    if canonical_goal_spec.get("status") == "PASS" and canonical_project_plan.get("status") == "PASS":
        candidates.append(_goal_plan_candidate(user_goal, canonical_goal_spec, canonical_project_plan))
    candidates.extend([_cloud_ai_candidate(user_goal), _small_demo_candidate(user_goal)])
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
    goal_spec = selected.get("canonical_goal_spec") if isinstance(selected.get("canonical_goal_spec"), dict) else {}
    project_plan = selected.get("canonical_project_plan") if isinstance(selected.get("canonical_project_plan"), dict) else {}
    if goal_spec:
        domain = str(goal_spec.get("domain", ""))
        direct_cli = domain == "local_record_cli"
        feature_unit = domain == "feature_unit_application"
        interaction_modes = requirement_decision_lane.goal_interaction_modes(goal_spec)
        visual_modes = {"web", "gui", "desktop"}.intersection(interaction_modes)
        architecture_mode = (
            "browser_local_static"
            if domain == "local_task_board"
            else "modular_authoring_studio"
            if domain == "visual_novel_editor"
            else "direct_cli_application"
            if direct_cli
            else "feature_unit_application"
            if feature_unit
            else "goal_driven_local_application"
        )
        return {
            "selected_id": selected["id"],
            "selected_name": selected["name"],
            "selection_reason": "Direct projection of the canonical GoalSpec and GoalDrivenProjectPlan for this request.",
            "architecture_mode": architecture_mode,
            "goal_spec_domain": str(goal_spec.get("domain", "")),
            "canonical_goal_spec": goal_spec,
            "canonical_project_plan": project_plan,
            "selected_project_summary": selected.get("summary", ""),
            "why_not_too_small": (
                "The user explicitly requested a minimal feature; fitness comes from frozen interfaces and executable behavior tests rather than unrelated module count."
                if feature_unit
                else f"Requires {len(stages)} goal-derived workstreams and {len(artifacts)} business outputs with behavior tests."
            ),
            "why_not_too_dependency_heavy": "Unrequested external integrations are excluded by the canonical goal constraints.",
            "why_deliverable": "The direction has explicit capabilities, workstreams, outputs, dependencies, and test intents.",
            "required_complexity_floor": {
                "min_pages": len(goal_spec.get("interfaces", [])),
                "min_modules": len(selected.get("likely_modules", [])),
                "min_pipeline_stages": 0 if direct_cli or feature_unit else len(stages),
                "min_stage_artifacts": 0 if feature_unit else len(artifacts),
                "requires_gui": bool(visual_modes),
                "requires_cli": "cli" in interaction_modes,
                "requires_shared_core": len(interaction_modes) > 1,
                "requires_runtime_evidence": True,
                "requires_final_bundle": True,
                "requires_screenshot": bool(visual_modes),
            },
        }
    task_board = selected.get("id") == "local_task_board"
    visual_novel = selected.get("id") == "local_visual_novel_studio"
    architecture_mode = (
        "browser_local_static"
        if task_board
        else "modular_authoring_studio"
        if visual_novel
        else "shared_core_pipeline"
    )
    return {
        "selected_id": selected["id"],
        "selected_name": selected["name"],
        "selection_reason": "Best weighted fit across complexity, local-first feasibility, pipeline clarity, artifact potential, GUI/CLI suitability, delivery feasibility, and testability.",
        "architecture_mode": architecture_mode,
        "why_not_too_small": (
            "Requires complete browser interactions, local persistence, automated tests, runtime evidence, screenshot, video, and final bundle without inventing a server-side domain core."
            if task_board
            else "Requires a typed story graph, independent image-generation adapters, asset binding, persistence, branch preview, planning documents, runtime evidence, screenshot, and final bundle."
            if visual_novel
            else f"Requires {len(stages)} pipeline stages, {len(artifacts)} stage artifacts, planning docs, shared core, CLI, GUI, runtime evidence, screenshot, and final bundle."
        ),
        "why_not_too_dependency_heavy": "External integrations are optional or degradable; the project can run locally with honest degraded mode.",
        "why_deliverable": "The selected shape has deterministic artifacts, local fixtures, shared core modules, and verifiable delivery evidence.",
        "required_complexity_floor": {
            "min_pages": max(1 if task_board else 6 if visual_novel else 4, len(selected.get("likely_pages", []))),
            "min_modules": max(4 if task_board else 8 if visual_novel else 6, len(selected.get("likely_modules", []))),
            "min_pipeline_stages": len(stages),
            "min_stage_artifacts": 0 if task_board else max(6, len(artifacts)),
            "requires_gui": True,
            "requires_cli": not task_board and not visual_novel,
            "requires_shared_core": not task_board,
            "requires_runtime_evidence": True,
            "requires_final_bundle": True,
            "requires_screenshot": True,
        },
    }


def build_contract(selected: dict[str, Any]) -> dict[str, Any]:
    goal_spec = selected.get("canonical_goal_spec") if isinstance(selected.get("canonical_goal_spec"), dict) else {}
    project_plan = selected.get("canonical_project_plan") if isinstance(selected.get("canonical_project_plan"), dict) else {}
    if goal_spec:
        structure = [str(item) for item in project_plan.get("expected_project_structure", [])]
        runtime_artifacts = [str(item) for item in project_plan.get("runtime_artifacts", project_plan.get("business_outputs", []))]
        task_board = str(goal_spec.get("domain", "")) == "local_task_board"
        visual_novel = str(goal_spec.get("domain", "")) == "visual_novel_editor"
        direct_cli = str(goal_spec.get("domain", "")) == "local_record_cli"
        feature_unit = str(goal_spec.get("domain", "")) == "feature_unit_application"
        interaction_modes = requirement_decision_lane.goal_interaction_modes(goal_spec)
        visual_modes = [
            mode for mode in interaction_modes if mode in {"web", "gui", "desktop"}
        ]
        architecture_mode = "browser_local_static" if task_board else "modular_authoring_studio" if visual_novel else "direct_cli_application" if direct_cli else "feature_unit_application" if feature_unit else "goal_driven_local_application"
        governance_core = [] if task_board or visual_novel or direct_cli or feature_unit else ["orchestrator.py", "stages.py"]
        governance_interfaces = (
            [str(item) for item in goal_spec.get("interfaces", [])]
            if task_board or visual_novel or feature_unit
            else interaction_modes
        )
        delivery_evidence = [
            item
            for item in DEFAULT_DELIVERY_EVIDENCE
            if item != "screenshot" or bool(visual_modes)
        ]
        return {
            "contract_id": "complexity_project_contract_v1",
            "architecture_mode": architecture_mode,
            "selected_project_id": selected["id"],
            "selected_project_name": selected["name"],
            "selected_project_summary": selected["summary"],
            "goal_spec_domain": str(goal_spec.get("domain", "")),
            "canonical_goal_spec": goal_spec,
            "canonical_project_plan": project_plan,
            "required_planning_docs": [] if direct_cli or feature_unit else ["goal_spec.json", "project_plan.json", "product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md"],
            "required_core_files": list(dict.fromkeys(governance_core + [path for path in structure if path.endswith(".py") and not path.startswith("tests/")])),
            "required_interfaces": list(dict.fromkeys(governance_interfaces)),
            "report_formats": list(goal_spec.get("report_formats", [])),
            "runtime_dependencies": list(goal_spec.get("runtime_dependencies", [])),
            "requires_shared_gui_cli_core": "cli" in interaction_modes and bool(visual_modes),
            "requires_screenshot": bool(visual_modes),
            "required_pipeline_stages": [] if direct_cli or feature_unit else [
                str(row.get("id", ""))
                for row in project_plan.get("workstreams", [])
                if isinstance(row, dict)
                and str(row.get("id", "")) not in {"foundation", "application_entry", "delivery"}
                and not str(row.get("id", "")).lower().endswith("_tests")
                and "behavior_tests" not in str(row.get("id", "")).lower()
            ],
            "required_stage_artifacts": [] if direct_cli or feature_unit else runtime_artifacts,
            "required_artifact_fields": DEFAULT_REQUIRED_ARTIFACT_FIELDS if runtime_artifacts and all(path.endswith(".json") for path in runtime_artifacts) else [],
            "required_delivery_evidence": delivery_evidence,
            "honest_degraded_mode_required": True,
            "forbidden_shortcuts": [
                item
                for item in FORBIDDEN_SHORTCUTS
                if not (feature_unit and item == "single_file_demo")
            ],
            "downstream_requirements": [
                "provider generation must implement the canonical GoalSpec capabilities and user flows",
                "component leaves must cite the canonical project plan workstreams and test intents",
                "unrelated product templates must not be introduced",
                *( ["feature interfaces and owned paths are frozen before dependency-ready parallel generation"] if feature_unit else [] ),
            ],
        }
    task_board = selected.get("id") == "local_task_board"
    visual_novel = selected.get("id") == "local_visual_novel_studio"
    planning_docs = (
        []
        if task_board
        else [
            "requirements.md",
            "product_design.md",
            "architecture.md",
            "interaction_design.md",
            "story_schema.md",
            "image_generation.md",
            "quality_plan.md",
            "test_plan.md",
        ]
        if visual_novel
        else [
            "product_brief.md",
            "technical_plan.md",
            "interaction_design.md",
            "acceptance_matrix.md",
        ]
    )
    return {
        "contract_id": "complexity_project_contract_v1",
        "architecture_mode": "browser_local_static" if task_board else "modular_authoring_studio" if visual_novel else "shared_core_pipeline",
        "selected_project_id": selected["id"],
        "selected_project_name": selected["name"],
        "selected_project_summary": selected["summary"],
        "required_planning_docs": planning_docs,
        "required_core_files": (
            ["main.py", "index.html", "app.js", "styles.css"]
            if task_board
            else ["story_graph.py", "asset_library.py", "image_adapters.py", "persistence.py", "preview.py"]
            if visual_novel
            else ["orchestrator.py", "stages.py"]
        ),
        "required_interfaces": ["web"] if task_board or visual_novel else ["cli", "gui"],
        "requires_shared_gui_cli_core": not task_board and not visual_novel,
        "required_pipeline_stages": list(selected.get("pipeline_stages", [])),
        "required_stage_artifacts": [] if task_board else list(selected.get("expected_artifacts", [])),
        "required_artifact_fields": [] if task_board else DEFAULT_REQUIRED_ARTIFACT_FIELDS,
        "required_delivery_evidence": DEFAULT_DELIVERY_EVIDENCE,
        "honest_degraded_mode_required": not task_board,
        "forbidden_shortcuts": FORBIDDEN_SHORTCUTS,
        "downstream_requirements": (
            ["provider generation must implement the selected browser-local direction without inventing a backend domain core"]
            if task_board
            else [
                *[f"{name} must cite complexity_project_contract.json" for name in planning_docs],
                "provider generation must implement the selected visual-novel authoring domain, not a video-processing pipeline",
                "background and transparent sprite generation must remain separate adapter workflows",
            ]
            if visual_novel
            else [
                "product_brief.md must cite complexity_project_contract.json",
                "technical_plan.md must cite complexity_project_contract.json",
                "interaction_design.md must cite complexity_project_contract.json",
                "acceptance_matrix.md must cite complexity_project_contract.json",
                "provider generation must implement the selected direction, not a generic version of the raw prompt",
            ]
        ),
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


def run_discovery_selection(
    user_goal: str,
    discovery_dir: pathlib.Path,
    *,
    candidate_count: int = 4,
    goal_spec: dict[str, Any] | None = None,
    project_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    discovery = pathlib.Path(discovery_dir)
    canonical_goal_spec = goal_spec or requirement_decision_lane.build_goal_spec(user_goal)
    canonical_project_plan = project_plan or requirement_decision_lane.build_goal_project_plan(canonical_goal_spec)
    candidates = generate_candidates(
        user_goal,
        candidate_count,
        goal_spec=canonical_goal_spec,
        project_plan=canonical_project_plan,
    )
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
    candidate_doc = {
        "user_goal": user_goal,
        "generated_at": now(),
        "goal_spec": canonical_goal_spec,
        "project_plan": canonical_project_plan,
        "candidates": candidates,
    }
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
        "goal_spec": canonical_goal_spec,
        "project_plan": canonical_project_plan,
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
