#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


RISK_VALUES = {"low", "medium", "high"}
STATUS_LAYERS = [
    "requirement_decision_status",
    "product_contract_status",
    "implementation_status",
    "delivery_status",
]
REQUIREMENT_ARTIFACTS = [
    "customer_goal_brief.md",
    "goal_spec.json",
    "project_plan.json",
    "need_interpretations.json",
    "candidate_requirements.json",
    "requirement_scorecard.json",
    "selected_requirement.json",
    "rejected_requirements.md",
    "mvp_scope.md",
    "non_goals.md",
    "customer_decision_summary.md",
]
FORBIDDEN_SHORTCUTS = [
    "direct_code_without_requirement_decision",
    "single_direction_without_comparison",
    "no_mvp_scope",
    "no_non_goals",
    "fake_pass",
    "delivery_pass_without_zip_or_screenshot",
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
    return value[:72] or "customer_requirement"


def product_domain_goal(raw_goal: str) -> str:
    """Exclude delivery-evidence clauses before inferring the product domain."""
    chunks = re.split(r"[\n。！？!?；;]+", str(raw_goal or "").lower())
    product_chunks = [
        chunk.strip()
        for chunk in chunks
        if chunk.strip() and not any(term in chunk for term in DELIVERY_EVIDENCE_TERMS)
    ]
    return "\n".join(product_chunks) or str(raw_goal or "").lower()


def goal_has_positive_term(raw_goal: str, terms: tuple[str, ...]) -> bool:
    clauses = re.split(r"[\n。！？!?；;，,]+", product_domain_goal(raw_goal))
    for clause in clauses:
        if not any(term in clause for term in terms):
            continue
        if any(marker in clause for marker in NEGATED_CAPABILITY_MARKERS):
            continue
        return True
    return False


def goal_has_media_product(raw_goal: str) -> bool:
    return goal_has_positive_term(raw_goal, MEDIA_PRODUCT_TERMS)


def goal_has_visual_novel_product(raw_goal: str) -> bool:
    domain_goal = product_domain_goal(raw_goal)
    return any(token in domain_goal for token in VISUAL_NOVEL_PRODUCT_TERMS)


def goal_has_task_board_product(raw_goal: str) -> bool:
    domain_goal = product_domain_goal(raw_goal)
    return any(token in domain_goal for token in TASK_BOARD_PRODUCT_TERMS)


def goal_has_specialized_analysis_product(raw_goal: str) -> bool:
    domain_goal = product_domain_goal(raw_goal)
    return any(token in domain_goal for token in SPECIALIZED_ANALYSIS_PRODUCT_TERMS)


def _contains_goal_term(goal: str, terms: tuple[str, ...]) -> bool:
    lowered = product_domain_goal(goal)
    return any(term in lowered for term in terms)


def _goal_profile(raw_goal: str) -> dict[str, Any] | None:
    goal = str(raw_goal or "").strip()
    lowered = product_domain_goal(goal)
    if not goal:
        return None
    if goal_has_visual_novel_product(goal):
        return {
            "domain": "visual_novel_editor",
            "capabilities": ["create_scenes", "manage_characters", "link_story_branches", "edit_dialogue", "preview_story_flow", "export_story_project"],
            "user_flows": ["create scenes and characters", "edit dialogue and connect story branches", "preview alternate story flow", "export and reload the story project"],
            "entities": ["StoryProject", "Scene", "Character", "Dialogue", "StoryBranch"],
            "interfaces": ["story_tree", "scene_editor", "character_editor", "branch_editor", "story_preview", "project_export"],
            "constraints": ["local_first", "persistent_project_state", "no_cloud_required"],
            "acceptance_behaviors": ["a scene can be created and edited", "a character can be created and assigned dialogue", "a branch can be linked to another scene", "edited dialogue survives save and export", "the user can preview and export the story flow"],
        }
    if _contains_goal_term(goal, ("pomodoro", "番茄钟", "work and break", "work/break")):
        return {
            "domain": "productivity_timer",
            "capabilities": ["start_timer", "pause_resume_timer", "reset_timer", "switch_work_break_cycle", "show_remaining_time"],
            "user_flows": ["start a configured work timer", "pause and resume the countdown", "reset the current session", "reach zero and switch between work and break phases"],
            "entities": ["TimerSession", "TimerSettings", "TimerPhase"],
            "interfaces": ["timer_view", "timer_controls", "phase_indicator", "timer_settings"],
            "constraints": ["local_first", "no_cloud_required", "countdown_state_is_deterministic"],
            "acceptance_behaviors": ["starting the timer decreases remaining time", "pausing the timer freezes the countdown", "resuming continues from the paused value", "reset restores the configured duration", "reaching zero switches the work or break phase"],
        }
    if "csv" in lowered and _contains_goal_term(goal, ("clean", "cleaning", "missing", "清洗", "缺失")):
        return {
            "domain": "csv_cleaning_tool",
            "capabilities": ["import_csv", "detect_missing_values", "configure_cleaning_rules", "apply_cleaning_rules", "preview_cleaned_result", "export_cleaned_csv"],
            "user_flows": ["import a local CSV file", "inspect missing values and choose cleaning rules", "preview the cleaned result", "export a new CSV file"],
            "entities": ["CsvDataset", "CsvColumn", "MissingValueFinding", "CleaningRule", "CleaningResult"],
            "interfaces": ["csv_import", "cleaning_rule_editor", "result_preview", "csv_export"],
            "constraints": ["local_first", "preserve_source_file", "no_cloud_required"],
            "acceptance_behaviors": ["a valid CSV parses into rows and columns", "missing values are detected", "selected cleaning rules transform matching values", "the preview reflects the cleaned result", "the cleaned dataset exports as a new CSV"],
        }
    if _contains_goal_term(goal, ("choreography", "dance sequence", "舞蹈编排", "舞谱")):
        return {
            "domain": "choreography_notation_editor",
            "capabilities": ["create_dance_sequence", "add_movement_notation", "arrange_sequence_timing", "edit_transition", "preview_choreography", "export_notation_project"],
            "user_flows": ["create a dance sequence", "add movements and timing", "edit transitions between movements", "preview and export the notation plan"],
            "entities": ["ChoreographyProject", "DanceSequence", "Movement", "Transition", "TimingCue"],
            "interfaces": ["sequence_editor", "movement_palette", "timing_track", "choreography_preview", "project_export"],
            "constraints": ["local_first", "editable_sequence_order", "no_cloud_required"],
            "acceptance_behaviors": ["a movement can be added to a sequence", "movement timing can be changed", "transitions preserve their linked movements", "the sequence can be previewed and exported"],
        }
    studio_operations_requested = (
        _contains_goal_term(goal, ("studio operations", "studio hub"))
        and _contains_goal_term(goal, ("asset", "production task", "bug", "release"))
    )
    if studio_operations_requested:
        return {
            "domain": "local_studio_operations_hub",
            "capabilities": ["show_project_dashboard", "track_production_tasks", "manage_asset_library", "track_bugs_and_issues", "record_build_and_release_history", "manage_release_checklist", "manage_team_roles", "search_operational_records", "import_export_workspace"],
            "user_flows": ["review project and production progress", "update tasks, assets, bugs, and release state", "search operational records", "import or export the local workspace"],
            "entities": ["StudioProject", "ProductionTask", "Asset", "Issue", "Build", "ReleaseChecklist", "TeamMember"],
            "interfaces": ["project_dashboard", "production_board", "asset_library", "issue_tracker", "release_view", "team_roles", "workspace_import_export"],
            "constraints": ["local_first", "no_external_saas_required"],
            "acceptance_behaviors": ["production progress is visible", "tasks, assets, issues, and releases retain their state", "operational records can be searched", "the workspace can be imported and exported"],
        }
    knowledge_requested = (
        _contains_goal_term(goal, ("knowledge studio", "knowledge workspace", "知识工作台", "知识库"))
        and _contains_goal_term(goal, ("document", "资料", "文档", "knowledge", "知识"))
    )
    if knowledge_requested:
        return {
            "domain": "local_ai_knowledge_studio",
            "capabilities": ["import_documents", "search_knowledge_base", "track_knowledge_tasks", "generate_reports", "configure_local_model_adapter"],
            "user_flows": ["import local documents", "search the indexed knowledge base", "create tasks from findings", "generate a report", "configure or inspect the local model adapter"],
            "entities": ["Document", "KnowledgeEntry", "KnowledgeTask", "Report", "ModelConfiguration"],
            "interfaces": ["document_import", "knowledge_search", "task_workspace", "report_view", "model_settings"],
            "constraints": ["local_first", "honest_model_capability", "no_cloud_required"],
            "acceptance_behaviors": ["an imported document becomes searchable", "knowledge search returns matching source content", "a task can be created from knowledge work", "a report summarizes selected sources and tasks", "missing model configuration is reported without claiming inference"],
        }
    if goal_has_task_board_product(goal):
        return {
            "domain": "local_task_board",
            "capabilities": ["create_task", "move_task_status", "delete_task", "filter_tasks", "persist_board_state"],
            "user_flows": ["create a task", "move it between board states", "filter visible tasks", "reload persisted board state", "delete a task"],
            "entities": ["Task", "TaskStatus", "BoardFilter"],
            "interfaces": ["task_board", "task_editor", "board_filters"],
            "constraints": ["local_first", "no_cloud_required"],
            "acceptance_behaviors": ["a task can be created", "task status can be changed", "filters change the visible task set", "board state survives reload", "a task can be deleted"],
        }
    if goal_has_media_product(goal):
        return {
            "domain": "local_media_workbench",
            "capabilities": ["import_media", "process_media_pipeline", "review_segments", "select_clips", "export_media_artifacts"],
            "user_flows": ["import local media", "run the processing stages", "review segments", "select clips", "export traceable artifacts"],
            "entities": ["MediaAsset", "PipelineRun", "Segment", "ClipSelection", "ExportManifest"],
            "interfaces": ["media_import", "pipeline_run", "segment_review", "clip_export"],
            "constraints": ["local_first", "honest_degraded_mode"],
            "acceptance_behaviors": ["imported media enters a traceable run", "stage results remain linked to the run", "segments can be reviewed and selected", "selected clips export with a manifest"],
        }
    if goal_has_specialized_analysis_product(goal):
        return {
            "domain": "specialized_analysis_workbench",
            "capabilities": ["register_authorized_sources", "acquire_authorized_input", "validate_input_provenance", "normalize_evidence", "analyze_explainable_features", "export_review_report"],
            "user_flows": ["register a reviewed source", "acquire authorized input", "validate and normalize evidence", "analyze explainable features", "export a human-review report"],
            "entities": ["SourceRegistry", "AcquisitionRecord", "EvidenceRecord", "FeatureFinding", "ReviewReport"],
            "interfaces": ["source_registry", "analysis_runs", "evidence_review", "report_export"],
            "constraints": ["authorized_inputs_only", "source_traceability", "no_automatic_punitive_decision"],
            "acceptance_behaviors": ["input provenance is retained", "invalid input is rejected", "analysis findings cite normalized evidence", "the exported report states limitations"],
        }
    if _contains_goal_term(goal, ("studio operations", "team operating", "团队管理", "indie team")):
        return {
            "domain": "team_operations_console",
            "capabilities": ["plan_milestones", "track_team_tasks", "link_project_assets", "record_decisions", "assess_risks", "export_release_status"],
            "user_flows": ["create a milestone", "assign and track work", "link assets and decisions", "review risks", "export release status"],
            "entities": ["Milestone", "TeamTask", "ProjectAsset", "Decision", "Risk", "ReleaseStatus"],
            "interfaces": ["team_dashboard", "milestone_board", "asset_links", "decision_log", "risk_review", "release_export"],
            "constraints": ["local_first", "traceable_status_changes"],
            "acceptance_behaviors": ["milestones retain linked tasks", "assets remain linked to work", "decisions and risks are reviewable", "release status can be exported"],
        }
    if _contains_goal_term(goal, ("research", "资料整理", "研究工作台")):
        return {
            "domain": "local_research_workspace",
            "capabilities": ["import_sources", "extract_source_metadata", "create_evidence_notes", "cluster_topics", "draft_traceable_brief", "export_evidence_pack"],
            "user_flows": ["import research sources", "create source-linked notes", "organize topics", "draft a brief", "export an evidence pack"],
            "entities": ["Source", "EvidenceNote", "TopicCluster", "ResearchBrief"],
            "interfaces": ["source_import", "notes_workspace", "topic_board", "brief_editor", "evidence_export"],
            "constraints": ["local_first", "source_traceability"],
            "acceptance_behaviors": ["an imported source retains provenance", "notes remain linked to sources", "topics group related notes", "the exported brief cites its evidence"],
        }
    words = re.findall(r"[a-z][a-z0-9_-]+|[\u4e00-\u9fff]{2,}", lowered)
    capability_rules = (
        ("create", "create_domain_record"), ("edit", "edit_domain_record"),
        ("plan", "plan_domain_workflow"), ("manage", "manage_domain_state"),
        ("track", "track_domain_state"), ("import", "import_domain_data"),
        ("export", "export_domain_result"), ("preview", "preview_domain_result"),
        ("analy", "analyze_domain_data"),
    )
    capabilities = [capability for marker, capability in capability_rules if marker in lowered]
    capabilities = list(dict.fromkeys(capabilities))
    if len(words) < 4 or len(capabilities) < 2:
        return None
    return {
        "domain": "custom_local_application",
        "capabilities": capabilities,
        "user_flows": ["provide domain input", "perform the requested domain workflow", "review and save the domain result"],
        "entities": ["DomainRecord", "ProjectState"],
        "interfaces": ["primary_workspace", "domain_editor", "result_view"],
        "constraints": ["local_first", "no_unrequested_external_service"],
        "acceptance_behaviors": [capability.replace("_", " ") + " behaves on user-provided data" for capability in capabilities],
    }


def build_goal_spec(raw_goal: str) -> dict[str, Any]:
    profile = _goal_profile(raw_goal)
    if profile is None:
        return {
            "kind": "GoalSpec",
            "status": "NEEDS_REWORK",
            "reason": "INSUFFICIENT_GOAL_PLAN",
            "goal": str(raw_goal or "").strip(),
            "domain": "generic_custom",
            "capabilities": [],
            "user_flows": [],
            "entities": [],
            "interfaces": [],
            "constraints": [],
            "acceptance_behaviors": [],
        }
    return {
        "kind": "GoalSpec",
        "status": "PASS",
        "goal": str(raw_goal or "").strip(),
        **profile,
    }


DOMAIN_WORKSTREAMS: dict[str, list[tuple[str, str]]] = {
    "productivity_timer": [
        ("timer_domain", "Model timer sessions, settings, phases, and valid transitions."),
        ("timer_state", "Implement start, pause, resume, reset, countdown, and work/break state changes."),
        ("timer_ui", "Expose remaining time, phase state, controls, and settings in the local interface."),
        ("timer_behavior_tests", "Verify countdown, pause, reset, and phase-switch behavior."),
    ],
    "csv_cleaning_tool": [
        ("csv_import", "Parse local CSV input and preserve source data and column shape."),
        ("cleaning_engine", "Detect missing values and apply explicit cleaning rules."),
        ("result_preview", "Present findings and the cleaned row/column result before export."),
        ("csv_export", "Write a new CSV without overwriting the source file."),
        ("cleaning_tests", "Verify parsing, missing-value transformation, preview, and export."),
    ],
    "visual_novel_editor": [
        ("story_model", "Model scenes, characters, dialogue, links, and branching story state."),
        ("scene_editor", "Create and edit scenes and dialogue."),
        ("character_editor", "Create characters and assign character dialogue and metadata."),
        ("branch_editor", "Connect scenes into validated branches and alternate paths."),
        ("preview_export", "Preview story flow and save or export the project."),
        ("story_behavior_tests", "Verify scene, character, branch, dialogue persistence, preview, and export behavior."),
    ],
    "choreography_notation_editor": [
        ("sequence_model", "Model dance sequences, movements, transitions, and timing cues."),
        ("notation_editor", "Create and edit movement notation."),
        ("movement_timeline", "Arrange movement order, timing, and transitions."),
        ("sequence_preview_export", "Preview choreography and export the notation project."),
        ("choreography_tests", "Verify movement editing, timing, transition integrity, preview, and export."),
    ],
    "local_ai_knowledge_studio": [
        ("document_import", "Import local documents and retain source metadata."),
        ("knowledge_search", "Index and search imported knowledge content."),
        ("task_reporting", "Create knowledge-work tasks and generate source-linked reports."),
        ("model_adapter", "Configure a local model adapter and report missing capability honestly."),
        ("knowledge_behavior_tests", "Verify import, search, task, report, and adapter-limit behavior."),
    ],
    "local_media_workbench": [
        ("ingest_video", "Import local media and record a traceable media manifest."),
        ("extract_audio", "Extract usable audio or record an honest degraded result."),
        ("build_audio_chunk_manifest", "Split audio into traceable chunks for transcription."),
        ("transcribe_chunks", "Transcribe available chunks through the configured capability."),
        ("merge_transcript", "Merge chunk transcripts while retaining source timing."),
        ("optional_analysis", "Analyze and score reviewable media segments."),
        ("select_segments", "Select candidate segments using explicit review criteria."),
        ("build_clip_manifest", "Build a clip manifest linked to selected segments."),
        ("render_clips_batch", "Render or honestly degrade the selected clip batch."),
        ("export_results", "Export reports, manifests, and selected media artifacts."),
        ("media_behavior_tests", "Verify import, traceability, review, selection, degraded-mode, and export behavior."),
    ],
    "specialized_analysis_workbench": [
        ("research_platform_sources", "Research and record reviewed official source capabilities and limitations."),
        ("acquire_authorized_input", "Acquire only authorized input while retaining provenance."),
        ("validate_and_normalize_evidence", "Validate input integrity and normalize traceable evidence records."),
        ("analyze_explainable_features", "Compute explainable features without making automatic punitive decisions."),
        ("render_evidence_report", "Export a human-review report that cites evidence and limitations."),
        ("specialized_analysis_tests", "Verify authorization, provenance, normalization, explainability, and report behavior."),
    ],
}

DOMAIN_RUNTIME_ARTIFACTS: dict[str, list[str]] = {
    "local_media_workbench": [
        "stage_plan.json",
        "media_manifest.json",
        "audio_chunk_manifest.json",
        "transcript_merged.json",
        "segment_analysis.json",
        "selected_segments.json",
        "clip_manifest.json",
        "export_results.json",
    ],
}


def _workstream_output(workstream_id: str) -> str:
    if workstream_id.endswith("_tests") or "behavior_tests" in workstream_id:
        return f"tests/test_{workstream_id}.py"
    return f"src/{workstream_id}.py"


def build_goal_project_plan(goal_spec: dict[str, Any]) -> dict[str, Any]:
    if goal_spec.get("status") != "PASS":
        return {
            "kind": "GoalDrivenProjectPlan",
            "status": "NEEDS_REWORK",
            "reason": goal_spec.get("reason", "INSUFFICIENT_GOAL_PLAN"),
            "workstreams": [],
            "leaves": [],
            "dependencies": [],
            "expected_project_structure": [],
            "business_outputs": [],
            "runtime_artifacts": [],
            "test_intents": [],
        }
    domain = str(goal_spec.get("domain", "custom_local_application"))
    definitions = DOMAIN_WORKSTREAMS.get(domain)
    if not definitions:
        definitions = [
            (str(capability), f"Implement and verify {str(capability).replace('_', ' ')} for the stated goal.")
            for capability in goal_spec.get("capabilities", [])
        ]
        definitions.append(("goal_behavior_tests", "Verify every acceptance behavior from the GoalSpec."))
    workstreams: list[dict[str, Any]] = []
    prior_ids: list[str] = []
    foundation = {
        "id": "foundation",
        "scope": "Create the runnable local project shell, dependency metadata, and shared domain contracts.",
        "depends_on": [],
        "expected_outputs": ["README.md", "pyproject.toml", "src/__init__.py", "app/main.py"],
        "test_intents": [],
    }
    workstreams.append(foundation)
    prior_ids.append("foundation")
    acceptance_behaviors = [str(item) for item in goal_spec.get("acceptance_behaviors", [])]
    for workstream_id, scope in definitions:
        is_test = workstream_id.endswith("_tests") or "behavior_tests" in workstream_id
        dependencies = list(prior_ids if is_test else ["foundation"])
        test_intents = acceptance_behaviors if is_test else []
        workstream = {
            "id": workstream_id,
            "scope": scope,
            "depends_on": dependencies,
            "expected_outputs": [_workstream_output(workstream_id)],
            "test_intents": test_intents,
        }
        workstreams.append(workstream)
        prior_ids.append(workstream_id)
    delivery_dependencies = [workstreams[-1]["id"]] if workstreams else ["foundation"]
    workstreams.append({
        "id": "delivery",
        "scope": "Document local startup, known constraints, and expected project contents for the existing delivery path.",
        "depends_on": delivery_dependencies,
        "expected_outputs": ["TEST_PLAN.md", "DELIVERY_NOTES.md"],
        "test_intents": [],
    })
    leaves = [
        {
            "leaf_id": f"{workstream['id']}_leaf",
            "workstream_id": workstream["id"],
            "scope": workstream["scope"],
            "depends_on": [f"{item}_leaf" for item in workstream["depends_on"]],
            "expected_outputs": list(workstream["expected_outputs"]),
            "test_intents": list(workstream["test_intents"]),
        }
        for workstream in workstreams
    ]
    expected_structure = list(dict.fromkeys(path for row in workstreams for path in row["expected_outputs"]))
    business_outputs = [path for path in expected_structure if path not in {"README.md", "pyproject.toml", "src/__init__.py", "app/main.py", "TEST_PLAN.md", "DELIVERY_NOTES.md"}]
    return {
        "kind": "GoalDrivenProjectPlan",
        "status": "PASS",
        "goal": goal_spec.get("goal", ""),
        "domain": domain,
        "workstreams": workstreams,
        "leaves": leaves,
        "dependencies": [{"from": dependency, "to": row["id"]} for row in workstreams for dependency in row["depends_on"]],
        "expected_project_structure": expected_structure,
        "business_outputs": business_outputs,
        "runtime_artifacts": list(DOMAIN_RUNTIME_ARTIFACTS.get(domain, business_outputs)),
        "test_intents": acceptance_behaviors,
    }


def _goal_candidate_id(domain: str) -> str:
    return {
        "local_media_workbench": "local_video_material_workbench_requirement",
        "local_task_board": "local_task_board_requirement",
        "visual_novel_editor": "local_visual_novel_studio_requirement",
        "local_research_workspace": "local_research_workspace_requirement",
        "local_ai_knowledge_studio": "local_ai_knowledge_studio_requirement",
        "specialized_analysis_workbench": "goal_derived_specialized_analysis_requirement",
        "team_operations_console": "indie_team_operating_console_requirement",
    }.get(domain, f"goal_derived_{slug(domain)}_requirement")


def candidate_from_goal_spec(goal_spec: dict[str, Any], project_plan: dict[str, Any]) -> dict[str, Any]:
    domain = str(goal_spec.get("domain", "custom_local_application"))
    title = domain.replace("_", " ").title()
    return _candidate(
        candidate_id=_goal_candidate_id(domain),
        name=title,
        summary=f"Goal-derived local product plan for: {goal_spec.get('goal', '')}",
        target_user="The user described by the current goal.",
        core_problem=f"Implement the requested {title} behavior without substituting an unrelated product template.",
        product_shape="Local-first application shaped by the declared interfaces and constraints.",
        mvp_features=[str(item).replace("_", " ") for item in goal_spec.get("capabilities", [])],
        non_goals=["Unrequested external services", "Unrelated product-domain capabilities"],
        core_workflow=[str(item) for item in goal_spec.get("user_flows", [])],
        pages=[str(item).replace("_", " ") for item in goal_spec.get("interfaces", [])],
        modules=[str(item.get("id", "")) for item in project_plan.get("workstreams", []) if item.get("id") not in {"foundation", "delivery"}],
        stages=[str(item.get("id", "")) for item in project_plan.get("workstreams", [])],
        artifacts=[str(item) for item in project_plan.get("business_outputs", [])],
        match="It is derived directly from the canonical GoalSpec for the current user goal.",
        wrong="The plan requires revision if the user changes the stated capabilities, flows, entities, or constraints.",
        complexity_level="complex",
        customer_value_score=99,
        clarity_score=98,
        local_first_feasibility=96,
        delivery_feasibility=94,
        testability_score=98,
        implementation_risk="low",
        demo_degradation_risk="low",
        fake_pass_risk="low",
        acceptance_summary="; ".join(str(item) for item in goal_spec.get("acceptance_behaviors", [])),
        degraded_mode=False,
    ) | {"goal_spec": goal_spec, "project_plan": project_plan}


def goal_is_complex(raw_goal: str, context: dict[str, Any] | None = None) -> bool:
    lowered = raw_goal.lower()
    if context and str(context.get("reference_complexity_target", "")).strip():
        return True
    return any(token in lowered for token in ("complex", "production", "workbench", "pipeline", "gui", "cli", "artifact", "复杂", "工作台", "流程", "本地", "团队", "研究"))


def risk_penalty(value: str) -> int:
    return {"low": 0, "medium": 8, "high": 28}.get(str(value), 28)


def generate_need_interpretations(raw_goal: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    goal = str(raw_goal or "").strip()
    lowered = goal.lower()
    interpreted: list[dict[str, Any]] = []
    if goal_has_visual_novel_product(goal):
        interpreted.append(
            {
                "id": "visual_novel_authoring_need",
                "need": "A local visual-novel authoring studio for branching story editing, generated backgrounds and transparent character sprites, asset binding, preview, and export.",
                "customer_problem": "The creator needs story structure and visual assets to remain editable and connected instead of becoming unrelated generated files.",
                "target_user": "Visual-novel writers and small creative teams.",
                "evidence_from_goal": product_domain_goal(goal)[:600],
                "assumptions": ["Offline procedural illustration may be an honestly labelled fallback when no diffusion model is configured."],
                "risk_if_wrong": "low",
            }
        )
    if goal_has_task_board_product(goal):
        interpreted.append(
            {
                "id": "task_board_need",
                "need": "A local task board for creating, moving, filtering, and persisting work items.",
                "customer_problem": "The customer needs a usable board workflow, while screenshots and demo video are delivery evidence rather than the product domain.",
                "target_user": "Individuals or small teams managing local tasks.",
                "evidence_from_goal": product_domain_goal(goal)[:600],
                "assumptions": ["Local browser persistence is sufficient for the first version."],
                "risk_if_wrong": "low",
            }
        )
    if goal_has_media_product(goal):
        interpreted.append(
            {
                "id": "media_workflow_need",
                "need": "A local-first media workflow that turns raw files into traceable review/export artifacts.",
                "customer_problem": "The customer likely needs repeatable processing and review, not just a video player or static demo.",
                "target_user": "Editors, operators, or solo creators managing local media material.",
                "evidence_from_goal": goal[:600],
                "assumptions": ["Local operation matters unless the customer explicitly asks for cloud processing."],
                "risk_if_wrong": "medium",
            }
        )
    if any(token in lowered for token in ("game", "studio", "team", "indie", "独立游戏", "团队", "项目管理")):
        interpreted.append(
            {
                "id": "team_management_need",
                "need": "A team operating system for planning work, tracking assets, decisions, risks, and release readiness.",
                "customer_problem": "The customer likely wants coordination and decision clarity, not a generic task board.",
                "target_user": "Small creative or engineering teams.",
                "evidence_from_goal": goal[:600],
                "assumptions": ["The first version should focus on project coordination rather than full enterprise governance."],
                "risk_if_wrong": "medium",
            }
        )
    if any(token in lowered for token in ("research", "资料", "整理", "knowledge", "study", "文档", "工作台")):
        interpreted.append(
            {
                "id": "research_workspace_need",
                "need": "A local research workspace that imports materials, extracts notes, links evidence, and produces reviewable briefs.",
                "customer_problem": "The customer likely needs structured knowledge work with traceability.",
                "target_user": "Researchers, analysts, founders, or operators handling local documents.",
                "evidence_from_goal": goal[:600],
                "assumptions": ["The first version can use deterministic local extraction and honest degraded mode."],
                "risk_if_wrong": "low",
            }
        )
    interpreted.append(
        {
            "id": "decision_clarity_need",
            "need": "A product that first clarifies the customer problem, scope, and acceptance criteria before implementation.",
            "customer_problem": "The raw goal may be underspecified and could otherwise collapse into a small demo.",
            "target_user": "The customer or internal operator who needs a clear first version.",
            "evidence_from_goal": goal[:600],
            "assumptions": ["CGKN should choose a deliverable MVP and expose non-goals."],
            "risk_if_wrong": "low",
        }
    )
    return {"raw_goal": goal, "interpreted_needs": interpreted[:4]}


def _candidate(
    *,
    candidate_id: str,
    name: str,
    summary: str,
    target_user: str,
    core_problem: str,
    product_shape: str,
    mvp_features: list[str],
    non_goals: list[str],
    core_workflow: list[str],
    pages: list[str],
    modules: list[str],
    stages: list[str],
    artifacts: list[str],
    match: str,
    wrong: str,
    complexity_level: str,
    customer_value_score: int,
    clarity_score: int,
    local_first_feasibility: int,
    delivery_feasibility: int,
    testability_score: int,
    implementation_risk: str,
    demo_degradation_risk: str,
    fake_pass_risk: str,
    acceptance_summary: str,
    degraded_mode: bool = True,
) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "name": name,
        "requirement_summary": summary,
        "target_user": target_user,
        "core_problem": core_problem,
        "product_shape": product_shape,
        "mvp_features": mvp_features,
        "non_goals": non_goals,
        "core_workflow": core_workflow,
        "likely_pages": pages,
        "likely_modules": modules,
        "pipeline_stages": stages,
        "expected_artifacts": artifacts,
        "why_it_matches_customer_goal": match,
        "why_it_might_be_wrong": wrong,
        "complexity_level": complexity_level,
        "customer_value_score": customer_value_score,
        "clarity_score": clarity_score,
        "local_first_feasibility": local_first_feasibility,
        "delivery_feasibility": delivery_feasibility,
        "testability_score": testability_score,
        "implementation_risk": implementation_risk,
        "demo_degradation_risk": demo_degradation_risk,
        "fake_pass_risk": fake_pass_risk,
        "acceptance_summary": acceptance_summary,
        "honest_degraded_mode_available": degraded_mode,
    }


def _small_demo_requirement() -> dict[str, Any]:
    return _candidate(
        candidate_id="single_static_page_demo_requirement",
        name="Single static page demo",
        summary="A one-page mockup with a few static cards.",
        target_user="A viewer of a prototype.",
        core_problem="Shows a rough visual idea but does not solve the operating workflow.",
        product_shape="Static preview only.",
        mvp_features=["Static cards"],
        non_goals=["Real workflow", "Artifacts", "Shared GUI/CLI core"],
        core_workflow=["open preview"],
        pages=["Home"],
        modules=["static_page"],
        stages=[],
        artifacts=[],
        match="It is fast and local.",
        wrong="It is too small and likely hides the real requirement.",
        complexity_level="small",
        customer_value_score=35,
        clarity_score=45,
        local_first_feasibility=98,
        delivery_feasibility=96,
        testability_score=30,
        implementation_risk="low",
        demo_degradation_risk="high",
        fake_pass_risk="high",
        acceptance_summary="A screenshot would exist, but it cannot validate the real customer workflow.",
    )


def _cloud_requirement() -> dict[str, Any]:
    return _candidate(
        candidate_id="cloud_ai_autopilot_requirement",
        name="Cloud AI autopilot requirement",
        summary="A fully automated cloud AI product using live model APIs, remote queues, and managed storage.",
        target_user="Teams with provisioned cloud AI infrastructure.",
        core_problem="Automation is attractive but risky when credentials and services are unknown.",
        product_shape="Cloud service dashboard.",
        mvp_features=["Cloud account setup", "Remote model jobs", "Remote storage", "Job monitor"],
        non_goals=[],
        core_workflow=["connect cloud", "submit remote job", "poll result"],
        pages=["Accounts", "Jobs", "Results"],
        modules=["cloud_client", "remote_jobs", "gui"],
        stages=["authenticate_cloud", "submit_model_jobs", "poll_remote_results"],
        artifacts=["remote_job_log.json"],
        match="It could fit an automation-heavy interpretation.",
        wrong="It depends on external accounts and is not safely deliverable as the first local version.",
        complexity_level="complex",
        customer_value_score=68,
        clarity_score=55,
        local_first_feasibility=30,
        delivery_feasibility=35,
        testability_score=40,
        implementation_risk="high",
        demo_degradation_risk="high",
        fake_pass_risk="high",
        acceptance_summary="Would require live external credentials and therefore cannot be honestly accepted by default.",
        degraded_mode=False,
    )


def generate_candidate_requirements(raw_goal: str, interpretations: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    goal_spec = build_goal_spec(raw_goal)
    project_plan = build_goal_project_plan(goal_spec)
    if goal_spec.get("status") == "PASS" and project_plan.get("status") == "PASS":
        candidates.append(candidate_from_goal_spec(goal_spec, project_plan))
    # Keep only domain-neutral rejected alternatives. Domain-specific fixed candidates
    # must never leak into a different user's planning output.
    for candidate in (_cloud_requirement(), _small_demo_requirement()):
        if not any(existing["id"] == candidate["id"] for existing in candidates):
            candidates.append(candidate)
    unique_candidates: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    for candidate in candidates:
        candidate_id = str(candidate.get("id", ""))
        if not candidate_id or candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(candidate_id)
        unique_candidates.append(candidate)
    return {
        "customer_goal": raw_goal,
        "generated_at": now(),
        "goal_spec": goal_spec,
        "project_plan": project_plan,
        "candidates": unique_candidates[:5],
    }


def rejection_reasons(candidate: dict[str, Any], *, complex_goal: bool = False) -> list[str]:
    reasons: list[str] = []
    if int(candidate.get("customer_value_score", 0)) < 50:
        reasons.append("customer_value_score_lt_50")
    if int(candidate.get("clarity_score", 0)) < 50:
        reasons.append("clarity_score_lt_50")
    if complex_goal and candidate.get("complexity_level") == "small":
        reasons.append("small_demo_for_complex_goal")
    if candidate.get("demo_degradation_risk") == "high":
        reasons.append("demo_degradation_risk_high")
    if candidate.get("fake_pass_risk") == "high":
        reasons.append("fake_pass_risk_high")
    if candidate.get("implementation_risk") == "high" and not candidate.get("honest_degraded_mode_available") and not candidate.get("non_goals"):
        reasons.append("high_implementation_risk_without_mvp_control")
    if not candidate.get("core_workflow"):
        reasons.append("core_workflow_missing")
    if not str(candidate.get("acceptance_summary", "")).strip():
        reasons.append("acceptance_summary_missing")
    return reasons


def score_total(candidate: dict[str, Any]) -> int:
    risk_control = 100 - min(70, risk_penalty(str(candidate.get("implementation_risk", "high"))) + risk_penalty(str(candidate.get("demo_degradation_risk", "high"))) + risk_penalty(str(candidate.get("fake_pass_risk", "high"))))
    complexity_fit = {"small": 35, "medium": 65, "complex": 85, "production_scale": 90}.get(str(candidate.get("complexity_level", "")), 50)
    mvp_focus = 80 if candidate.get("mvp_features") and candidate.get("non_goals") else 45
    score = (
        int(candidate.get("customer_value_score", 0)) * 0.22
        + int(candidate.get("clarity_score", 0)) * 0.16
        + complexity_fit * 0.14
        + int(candidate.get("local_first_feasibility", 0)) * 0.12
        + int(candidate.get("delivery_feasibility", 0)) * 0.14
        + int(candidate.get("testability_score", 0)) * 0.1
        + mvp_focus * 0.07
        + risk_control * 0.05
    )
    return max(0, min(100, round(score)))


def score_candidate_requirements(candidates: dict[str, Any] | list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_candidates = candidates.get("candidates", []) if isinstance(candidates, dict) else candidates
    complex_goal = bool((context or {}).get("complex_goal"))
    scores = []
    for candidate in raw_candidates if isinstance(raw_candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        reasons = rejection_reasons(candidate, complex_goal=complex_goal)
        total = score_total(candidate)
        selectable = (
            not reasons
            and int(candidate.get("customer_value_score", 0)) >= 70
            and int(candidate.get("clarity_score", 0)) >= 70
            and int(candidate.get("delivery_feasibility", 0)) >= 65
            and int(candidate.get("testability_score", 0)) >= 65
        )
        scores.append(
            {
                "candidate_id": candidate.get("id", ""),
                "candidate_name": candidate.get("name", ""),
                "total_score": total,
                "decision": "select" if selectable else "reject",
                "reason": "eligible_requirement_direction" if selectable else ", ".join(reasons or ["lower_score_or_weaker_fit"]),
                "customer_value_score": candidate.get("customer_value_score", 0),
                "clarity_score": candidate.get("clarity_score", 0),
                "complexity_fit": {"small": 35, "medium": 65, "complex": 85, "production_scale": 90}.get(str(candidate.get("complexity_level", "")), 50),
                "local_first_feasibility": candidate.get("local_first_feasibility", 0),
                "delivery_feasibility": candidate.get("delivery_feasibility", 0),
                "testability_score": candidate.get("testability_score", 0),
                "mvp_focus": 80 if candidate.get("mvp_features") and candidate.get("non_goals") else 45,
                "risk_control": 100 - min(70, risk_penalty(str(candidate.get("implementation_risk", "high"))) + risk_penalty(str(candidate.get("demo_degradation_risk", "high"))) + risk_penalty(str(candidate.get("fake_pass_risk", "high")))),
            }
        )
    return {
        "scoring_dimensions": [
            "customer_value_score",
            "clarity_score",
            "complexity_fit",
            "local_first_feasibility",
            "delivery_feasibility",
            "testability_score",
            "mvp_focus",
            "risk_control",
        ],
        "scores": scores,
    }


def select_requirement(candidates: dict[str, Any] | list[dict[str, Any]], scorecard: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_candidates = candidates.get("candidates", []) if isinstance(candidates, dict) else candidates
    by_id = {str(candidate.get("id", "")): candidate for candidate in raw_candidates if isinstance(candidate, dict)}
    eligible = [score for score in scorecard.get("scores", []) if isinstance(score, dict) and score.get("decision") == "select"]
    if not eligible:
        return {
            "status": "NEEDS_REWORK",
            "selected_requirement_id": "",
            "selected_requirement_name": "",
            "reason": "No candidate requirement satisfied value, clarity, feasibility, testability, and risk thresholds.",
        }
    best = sorted(eligible, key=lambda item: int(item.get("total_score", 0)), reverse=True)[0]
    candidate = by_id[str(best.get("candidate_id", ""))]
    rejected = [score for score in scorecard.get("scores", []) if isinstance(score, dict) and score.get("candidate_id") != candidate.get("id")]
    return {
        "selected_requirement_id": candidate["id"],
        "selected_requirement_name": candidate["name"],
        "customer_goal": candidates.get("customer_goal", "") if isinstance(candidates, dict) else "",
        "interpreted_need": candidate["requirement_summary"],
        "target_user": candidate["target_user"],
        "core_problem": candidate["core_problem"],
        "selected_product_shape": candidate["product_shape"],
        "why_this_requirement": [
            candidate["why_it_matches_customer_goal"],
            "It has enough value, clarity, delivery feasibility, testability, MVP boundaries, and risk control for a first build.",
        ],
        "why_not_other_requirements": [f"{item.get('candidate_id')}: {item.get('reason')}" for item in rejected],
        "mvp_scope": candidate["mvp_features"],
        "non_goals": candidate["non_goals"],
        "acceptance_summary": candidate["acceptance_summary"],
        "known_assumptions": ["The selected MVP can be revised if the customer rejects the chosen direction."],
        "open_questions_not_blocking": ["Confirm exact runtime platform and preferred UI style before final polish."],
        "decision_confidence": "high" if int(best.get("total_score", 0)) >= 80 else "medium",
        "goal_spec": candidate.get("goal_spec", {}),
        "project_plan": candidate.get("project_plan", {}),
    }


def build_acceptance_contract(selected: dict[str, Any]) -> dict[str, Any]:
    goal_spec = selected.get("goal_spec", {}) if isinstance(selected.get("goal_spec"), dict) else {}
    project_plan = selected.get("project_plan", {}) if isinstance(selected.get("project_plan"), dict) else {}
    return {
        "contract_id": "requirement_acceptance_contract_v1",
        "selected_requirement_id": selected.get("selected_requirement_id", ""),
        "success_definition": selected.get("acceptance_summary", ""),
        "required_planning_docs": ["product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md"],
        "required_requirement_artifacts": REQUIREMENT_ARTIFACTS,
        "required_product_outputs": [],
        "required_delivery_evidence": ["README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md", "run_dir"],
        "implementation_delivery_evidence": ["final_project_bundle.zip", "screenshot"],
        "acceptance_behaviors": list(goal_spec.get("acceptance_behaviors", [])),
        "test_intents": list(project_plan.get("test_intents", [])),
        "status_layers": STATUS_LAYERS,
        "forbidden_shortcuts": FORBIDDEN_SHORTCUTS,
    }


def customer_goal_brief(raw_goal: str, interpretations: dict[str, Any]) -> str:
    needs = interpretations.get("interpreted_needs", []) if isinstance(interpretations, dict) else []
    primary = needs[0] if needs else {}
    return "\n".join(
        [
            "# Customer Goal Brief",
            "",
            f"Raw customer goal: {raw_goal}",
            "",
            f"CGKN interpretation: {primary.get('need', 'The customer needs a clearer product requirement before implementation.')}",
            "",
            "Key uncertainties:",
            "- Exact user role and daily workflow may need confirmation.",
            "- Runtime platform and dependency constraints may need confirmation.",
            "- Whether external services are allowed is not assumed.",
            "",
            "Known constraints:",
            "- Requirement decision must precede implementation.",
            "- Delivery success still requires evidence, not only a decision summary.",
            "",
            "Do not directly assume:",
            "- That a static demo is enough.",
            "- That cloud APIs or live models are available.",
            "- That generated code can pass without requirement alignment.",
            "",
            "CGKN autonomous decisions needed:",
            "- Choose the best first product requirement.",
            "- Freeze MVP scope, non-goals, and acceptance criteria.",
        ]
    ) + "\n"


def rejected_markdown(candidates: list[dict[str, Any]], scorecard: dict[str, Any], selected_id: str) -> str:
    scores = {str(item.get("candidate_id", "")): item for item in scorecard.get("scores", []) if isinstance(item, dict)}
    lines = ["# Rejected Requirements", ""]
    for candidate in candidates:
        if candidate.get("id") == selected_id:
            continue
        score = scores.get(str(candidate.get("id", "")), {})
        lines.extend(
            [
                f"## {candidate.get('name', '')}",
                "",
                f"- id: `{candidate.get('id', '')}`",
                f"- reason: {score.get('reason', 'not selected')}",
                f"- risk type: implementation={candidate.get('implementation_risk')}, demo={candidate.get('demo_degradation_risk')}, fake_pass={candidate.get('fake_pass_risk')}",
                f"- future version: {'yes' if candidate.get('demo_degradation_risk') != 'high' and candidate.get('fake_pass_risk') != 'high' else 'no, unless reframed'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def mvp_scope_markdown(selected: dict[str, Any]) -> str:
    must = selected.get("mvp_scope", []) if isinstance(selected.get("mvp_scope"), list) else []
    return "\n".join(
        [
            "# MVP Scope",
            "",
            "## Must Do This Round",
            *[f"- {item}" for item in must[:4]],
            "",
            "## Should Do This Round",
            *[f"- {item}" for item in must[4:]],
            "",
            "## Not This Round",
            *[f"- {item}" for item in selected.get("non_goals", [])],
            "",
            "## Later Versions",
            "- Customer-specific integrations after the first requirement is validated.",
            "- Larger automation or cloud workflows after credentials and acceptance evidence are agreed.",
            "",
            "## Scope Rationale",
            "This scope preserves the selected requirement while keeping the first version testable and deliverable.",
        ]
    ) + "\n"


def non_goals_markdown(selected: dict[str, Any]) -> str:
    lines = ["# Non-Goals", ""]
    for item in selected.get("non_goals", []) if isinstance(selected.get("non_goals"), list) else []:
        lines.extend([f"## {item}", "", "- Reason: outside the selected MVP or too risky for first delivery.", "- Risk if forced now: larger dependency surface, weaker testing, and higher fake-pass risk.", ""])
    if len(lines) == 2:
        lines.extend(["- No explicit non-goals were selected; this should be reworked before implementation.", ""])
    return "\n".join(lines).rstrip() + "\n"


def customer_summary_markdown(selected: dict[str, Any], scorecard: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Customer Decision Summary",
            "",
            f"I understand your goal as: {selected.get('interpreted_need', '')}",
            "",
            "I compared multiple directions and selected:",
            f"- {selected.get('selected_requirement_name', '')}",
            "",
            "Why this requirement:",
            *[f"- {item}" for item in selected.get("why_this_requirement", [])],
            "",
            "MVP for this round:",
            *[f"- {item}" for item in selected.get("mvp_scope", [])],
            "",
            "Not doing this round:",
            *[f"- {item}" for item in selected.get("non_goals", [])],
            "",
            "Next step:",
            "- Use the selected requirement, MVP scope, non-goals, and acceptance contract as input to product design and implementation.",
            "",
            "If you disagree, the adjustable points are target user, workflow scope, non-goals, and acceptance criteria.",
        ]
    ) + "\n"


def write_requirement_decision_artifacts(result: dict[str, Any], run_dir: pathlib.Path) -> dict[str, str]:
    base = pathlib.Path(run_dir) / "requirement_decision"
    interpretations = result.get("need_interpretations", {})
    candidate_doc = result.get("candidate_requirements", {})
    candidates = candidate_doc.get("candidates", []) if isinstance(candidate_doc, dict) else []
    scorecard = result.get("requirement_scorecard", {})
    selected = result.get("selected_requirement", {})
    contract = result.get("acceptance_contract", {})
    goal_spec = result.get("goal_spec", {})
    project_plan = result.get("project_plan", {})
    paths = {
        "customer_goal_brief": str(base / "customer_goal_brief.md"),
        "goal_spec": str(base / "goal_spec.json"),
        "project_plan": str(base / "project_plan.json"),
        "need_interpretations": str(base / "need_interpretations.json"),
        "candidate_requirements": str(base / "candidate_requirements.json"),
        "requirement_scorecard": str(base / "requirement_scorecard.json"),
        "selected_requirement": str(base / "selected_requirement.json"),
        "rejected_requirements": str(base / "rejected_requirements.md"),
        "mvp_scope": str(base / "mvp_scope.md"),
        "non_goals": str(base / "non_goals.md"),
        "acceptance_contract": str(base / "acceptance_contract.json"),
        "customer_decision_summary": str(base / "customer_decision_summary.md"),
    }
    write_text(pathlib.Path(paths["customer_goal_brief"]), customer_goal_brief(str(result.get("raw_goal", "")), interpretations))
    write_json(pathlib.Path(paths["goal_spec"]), goal_spec)
    write_json(pathlib.Path(paths["project_plan"]), project_plan)
    write_json(pathlib.Path(paths["need_interpretations"]), interpretations)
    write_json(pathlib.Path(paths["candidate_requirements"]), candidate_doc)
    write_json(pathlib.Path(paths["requirement_scorecard"]), scorecard)
    write_json(pathlib.Path(paths["selected_requirement"]), selected)
    write_text(pathlib.Path(paths["rejected_requirements"]), rejected_markdown(candidates, scorecard, str(selected.get("selected_requirement_id", ""))))
    write_text(pathlib.Path(paths["mvp_scope"]), mvp_scope_markdown(selected))
    write_text(pathlib.Path(paths["non_goals"]), non_goals_markdown(selected))
    write_json(pathlib.Path(paths["acceptance_contract"]), contract)
    write_text(pathlib.Path(paths["customer_decision_summary"]), customer_summary_markdown(selected, scorecard))
    return paths


def load_requirement_acceptance_contract(run_dir: pathlib.Path) -> dict[str, Any]:
    return read_json(pathlib.Path(run_dir) / "requirement_decision" / "acceptance_contract.json")


def run_requirement_decision(raw_goal: str, run_dir: pathlib.Path, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(context or {})
    context.setdefault("complex_goal", goal_is_complex(raw_goal, context))
    goal_spec = build_goal_spec(raw_goal)
    project_plan = build_goal_project_plan(goal_spec)
    interpretations = generate_need_interpretations(raw_goal, context)
    candidates = generate_candidate_requirements(raw_goal, interpretations, context)
    if goal_spec.get("status") == "PASS" and project_plan.get("status") == "PASS":
        scorecard = score_candidate_requirements(candidates, context)
        selected = select_requirement(candidates, scorecard, context)
    else:
        scorecard = {"scores": [], "status": "NEEDS_REWORK", "reason": "INSUFFICIENT_GOAL_PLAN"}
        selected = {
            "status": "NEEDS_REWORK",
            "selected_requirement_id": "",
            "selected_requirement_name": "",
            "reason": "INSUFFICIENT_GOAL_PLAN",
            "goal_spec": goal_spec,
            "project_plan": project_plan,
        }
    status = "PASS" if selected.get("selected_requirement_id") else "NEEDS_REWORK"
    contract = build_acceptance_contract(selected) if status == "PASS" else {
        "contract_id": "requirement_acceptance_contract_v1",
        "status": "NEEDS_REWORK",
        "reason": selected.get("reason", "No selected requirement."),
        "status_layers": STATUS_LAYERS,
        "forbidden_shortcuts": FORBIDDEN_SHORTCUTS,
    }
    result = {
        "status": status,
        "raw_goal": raw_goal,
        "goal_spec": goal_spec,
        "project_plan": project_plan,
        "need_interpretations": interpretations,
        "candidate_requirements": candidates,
        "requirement_scorecard": scorecard,
        "selected_requirement": selected,
        "acceptance_contract": contract,
    }
    result["paths"] = write_requirement_decision_artifacts(result, pathlib.Path(run_dir))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_requirement_decision(args.goal, pathlib.Path(args.run_dir))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"REQUIREMENT_DECISION: {result['status']}")
        print(f"requirement_decision_dir={pathlib.Path(args.run_dir).resolve() / 'requirement_decision'}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
