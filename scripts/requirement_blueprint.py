#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


AGENT_SEQUENCE = [
    "RequirementAgent",
    "IOContractAgent",
    "GapAgent",
    "FeatureAgent",
    "CapabilityAgent",
    "TechSearchAgent",
    "TechDecisionAgent",
    "BlueprintAgent",
    "TaskAgent",
    "ReviewAgent",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in terms)


def wants_game_video_highlight(requirement: str) -> bool:
    lowered = str(requirement or "").lower()
    has_video = any(term in lowered for term in ("视频", "video", "录像", "录屏", "gameplay", "vod"))
    has_game = any(term in lowered for term in ("游戏", "game", "gameplay"))
    has_highlight = any(term in lowered for term in ("高光", "highlight", "精彩", "clip", "片段"))
    return has_video and has_game and has_highlight


def source_value(value: Any, source_type: str, confidence: float) -> dict[str, Any]:
    return {"value": value, "source_type": source_type, "confidence": round(confidence, 2)}


def answer_map(answers: list[dict[str, str]] | None) -> dict[str, str]:
    return {str(row.get("field", "")): str(row.get("answer", "")) for row in answers or []}


def infer_project_type(requirement: str) -> str:
    if wants_game_video_highlight(requirement):
        return "game_video_highlight_finder"
    if contains_any(requirement, ("蓝图", "需求", "prd", "技术方案", "任务清单", "requirement", "blueprint")):
        return "requirement_blueprint_generator"
    if contains_any(requirement, ("看板", "任务", "工单", "kanban", "ticket", "board")):
        return "local_management_board"
    if contains_any(requirement, ("直播", "主播", "高光", "clip", "highlight", "streamer")):
        return "streamer_highlight_tool"
    if contains_any(requirement, ("报告", "报表", "report", "dashboard", "统计")):
        return "reporting_dashboard"
    return "custom_application"


def infer_target_users(requirement: str, answers: dict[str, str]) -> list[str]:
    explicit = answers.get("target_user", "").strip()
    if explicit:
        return [explicit]
    if contains_any(requirement, ("学生", "课程", "答辩")):
        return ["students_or_course_project_team"]
    if contains_any(requirement, ("开发", "技术", "api", "数据库", "代码")):
        return ["developer_or_technical_lead"]
    if contains_any(requirement, ("客服", "客户", "工单")):
        return ["support_team", "operations_manager"]
    if contains_any(requirement, ("主播", "直播", "剪辑")):
        return ["streamer_operator", "content_editor"]
    return ["project_owner", "developer"]


def build_requirement_spec(requirement: str, answers: dict[str, str]) -> dict[str, Any]:
    project_type = infer_project_type(requirement)
    if wants_game_video_highlight(requirement):
        return {
            "project_type": source_value(project_type, "inferred", 0.9),
            "business_goal": source_value(
                "Build a runnable tool that accepts one arbitrary game video, detects highlight moments with multiple signals, and exports MP4 highlight clips plus an explainable timeline.",
                "explicit",
                0.95,
            ),
            "target_users": source_value(["content_editor", "streamer_operator", "game_video_creator"], "inferred", 0.82),
            "scenarios": [
                source_value("User selects one local gameplay video file.", "explicit", 0.96),
                source_value("System analyzes visual motion, audio peaks, speech/subtitle keywords, and dense event windows.", "explicit", 0.92),
                source_value("User reviews ranked highlight candidates and exports separate MP4 clips.", "explicit", 0.9),
            ],
            "pain_points": [
                source_value("Manual highlight finding requires repeatedly scrubbing through long gameplay footage.", "inferred", 0.86),
                source_value("Single-signal detection misses highlights when the excitement is visual, audio, or language-only.", "inferred", 0.84),
                source_value("Editors need tunable sensitivity and minimum duration instead of fixed clip rules.", "explicit", 0.86),
            ],
            "scope_boundary": [
                source_value(
                    "V1 runs locally with one uploaded/selected game video at a time; it produces ranked candidates, MP4 clips or a cut manifest, and an analysis report.",
                    "assumed",
                    0.8,
                ),
            ],
        }
    target_users = infer_target_users(requirement, answers)
    core_answer = answers.get("core_features", "").strip()
    return {
        "project_type": source_value(project_type, "inferred", 0.72),
        "business_goal": source_value(clean_text(requirement) or "Turn a user request into a buildable project plan.", "explicit", 0.95),
        "target_users": source_value(target_users, "inferred" if not answers.get("target_user") else "explicit", 0.76),
        "scenarios": [
            source_value("User submits a natural-language project request.", "explicit", 0.9),
            source_value("System analyzes input, output, gaps, features, capabilities, and tasks.", "assumed", 0.75),
            source_value("Developer reviews generated blueprint artifacts before implementation.", "assumed", 0.72),
        ],
        "pain_points": [
            source_value("Requirement wording is likely underspecified at first contact.", "inferred", 0.8),
            source_value("Implementation tasks need traceability to inputs, outputs, and acceptance criteria.", "assumed", 0.82),
            source_value("Technology choices should be tied to capabilities instead of broad project labels.", "assumed", 0.82),
        ],
        "scope_boundary": [
            source_value(core_answer or "Generate a concrete blueprint and then continue through the existing CGNK project generation flow.", "assumed" if not core_answer else "explicit", 0.72),
        ],
    }


def build_io_contract(requirement: str, requirement_spec: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    if wants_game_video_highlight(requirement):
        return {
            "input_contract": {
                "input_sources": [
                    source_value("Single local game video file selected by the user.", "explicit", 0.96),
                ],
                "input_types": ["video_file"],
                "required_fields": ["game_video_file"],
                "optional_fields": ["min_highlight_duration", "sensitivity", "output_format"],
                "unknowns": [],
            },
            "process_contract": {
                "main_process": "Analyze one local game video and produce ranked highlight clips without requiring pre-labeled event records.",
                "steps": [
                    "VideoInputAgent",
                    "VideoMetadataAgent",
                    "FrameSignalAgent",
                    "AudioSignalAgent",
                    "SpeechOrSubtitleSignalAgent",
                    "HighlightCandidateAgent",
                    "MultiCriteriaScoringAgent",
                    "ClipBoundaryAgent",
                    "ExportAgent",
                    "ReviewAgent",
                ],
                "state_transitions": [
                    "video_selected",
                    "metadata_extracted",
                    "frame_signals_sampled",
                    "audio_signals_sampled",
                    "candidate_windows_generated",
                    "candidates_scored",
                    "clip_boundaries_selected",
                    "mp4_exports_created_or_cutlist_ready",
                    "reviewed",
                ],
            },
            "output_contract": {
                "output_types": ["highlight_video_files", "highlight_timeline", "clip_manifest", "analysis_report"],
                "output_formats": ["mp4", "json", "markdown"],
                "consumers": requirement_spec.get("target_users", {}).get("value", ["streamer_operator", "content_editor"]),
                "storage": source_value("Persist analysis state locally; exported highlight clips should preserve source video quality where possible.", "explicit", 0.82),
                "unknowns": [],
            },
        }
    wants_docs = contains_any(requirement, ("word", "pdf", "excel", "文档", "上传", "文件"))
    wants_export = contains_any(requirement, ("导出", "export", "csv", "markdown", "pdf", "word"))
    storage_answer = answers.get("data_storage", "").strip()
    return {
        "input_contract": {
            "input_sources": [
                source_value("Natural-language requirement entered by the user.", "explicit", 0.96),
                source_value("Optional uploaded requirement documents.", "inferred" if wants_docs else "unknown", 0.62 if wants_docs else 0.35),
            ],
            "input_types": ["plain_text", "document"] if wants_docs else ["plain_text"],
            "required_fields": ["project_goal", "requirement_description"],
            "optional_fields": ["target_user", "tech_preference", "deadline", "budget", "existing_documents"],
            "unknowns": [] if wants_docs else ["Whether uploaded documents need to be supported in this version."],
        },
        "process_contract": {
            "main_process": "Convert raw user intent into traceable engineering blueprint artifacts.",
            "steps": AGENT_SEQUENCE,
            "state_transitions": [
                "created",
                "requirement_submitted",
                "requirement_analyzed",
                "io_analyzed",
                "gap_checked",
                "io_confirmed",
                "features_generated",
                "capabilities_mapped",
                "tech_discovered",
                "tech_decided",
                "blueprint_generated",
                "tasks_generated",
                "reviewed",
            ],
        },
        "output_contract": {
            "output_types": [
                "requirement_spec",
                "io_contract",
                "feature_spec",
                "capability_map",
                "tech_candidates",
                "tech_decisions",
                "architecture_diagram",
                "api_spec",
                "db_schema",
                "frontend_pages",
                "task_backlog",
                "prd",
            ],
            "output_formats": ["json", "markdown", "mermaid", "openapi_yaml", "sql", "csv"],
            "consumers": requirement_spec.get("target_users", {}).get("value", ["developer", "project_manager"]),
            "storage": source_value(storage_answer or "Persist runtime artifacts as local JSON/Markdown files; generated apps may use localStorage unless a database is requested.", "explicit" if storage_answer else "assumed", 0.74),
            "unknowns": [] if wants_export else ["Whether Word/PDF export is required beyond Markdown/JSON/CSV."],
        },
    }


def build_gap_analysis(requirement: str, answers: dict[str, str], assume_defaults: bool) -> dict[str, Any]:
    if wants_game_video_highlight(requirement):
        return {
            "gap_items": [
                {
                    "question": "What is the runtime input?",
                    "severity": "Level 3",
                    "impact": "Defines whether the generated project should ask for a video file or pre-labeled event data.",
                    "default_assumption": "Use exactly one local game video file.",
                    "status": "resolved",
                },
                {
                    "question": "How should highlights be judged?",
                    "severity": "Level 3",
                    "impact": "Controls feature modules and the scoring pipeline.",
                    "default_assumption": "Fuse visual motion, audio peaks, speech/subtitle keywords, and short-window event density.",
                    "status": "resolved",
                },
                {
                    "question": "What outputs are required?",
                    "severity": "Level 3",
                    "impact": "Controls export modules and acceptance tests.",
                    "default_assumption": "Export separate MP4 clips plus a JSON manifest and readable analysis report.",
                    "status": "resolved",
                },
                {
                    "question": "Which settings must the user control in v1?",
                    "severity": "Level 2",
                    "impact": "Affects UI controls and scoring defaults.",
                    "default_assumption": "Expose minimum highlight duration and sensitivity.",
                    "status": "resolved",
                },
            ],
            "can_continue": True,
        }
    gaps: list[dict[str, Any]] = []

    def add(question: str, severity: str, impact: str, default: str | None, resolved: bool) -> None:
        gaps.append(
            {
                "question": question,
                "severity": severity,
                "impact": impact,
                "default_assumption": default,
                "status": "resolved" if resolved else "open",
            }
        )

    code_known = contains_any(requirement, ("代码", "可运行", "网站", "app", "应用", "生成项目", "generate code", "running app")) or bool(answers.get("acceptance"))
    add(
        "Should the flow generate runnable project files, or only a requirements blueprint?",
        "Level 3",
        "Controls whether CGNK continues into project materialization, tests, and effect reports.",
        "Generate runnable local project files plus blueprint artifacts.",
        code_known or assume_defaults,
    )
    add(
        "Are Word/PDF exports required in v1?",
        "Level 2",
        "Affects document export library choices and artifact packaging.",
        "Export Markdown, JSON, Mermaid, OpenAPI YAML, SQL, and CSV first.",
        assume_defaults or contains_any(requirement, ("word", "pdf", "导出", "export")),
    )
    add(
        "Is multi-user collaboration required?",
        "Level 2",
        "Affects account, permission, project versioning, and database design.",
        "Treat v1 as a single-user local workflow.",
        assume_defaults or contains_any(requirement, ("协作", "多人", "团队", "权限")),
    )
    add(
        "Are external integrations such as GitHub, Jira, Feishu, Telegram, or provider APIs allowed?",
        "Level 2",
        "Affects network policy, credentials, and human approval gates.",
        "Keep external calls disabled unless explicitly approved.",
        assume_defaults or contains_any(requirement, ("github", "jira", "飞书", "telegram", "api")),
    )
    unresolved_level3 = [gap for gap in gaps if gap["severity"] == "Level 3" and gap["status"] != "resolved"]
    return {"gap_items": gaps, "can_continue": not unresolved_level3}


def build_feature_spec(requirement: str, answers: dict[str, str]) -> dict[str, Any]:
    if wants_game_video_highlight(requirement):
        features = [
            ("Video intake", "Accept exactly one local game video file as the runtime input.", ["game_video_file"], ["video_asset"]),
            ("Video metadata extraction", "Read duration, mime type, file size, and preview metadata.", ["video_asset"], ["video_metadata"]),
            ("Frame signal extraction", "Sample visual/motion signal windows from the video timeline.", ["video_asset", "video_metadata"], ["frame_samples"]),
            ("Audio signal extraction", "Detect audio peak and intensity windows that may indicate exciting moments.", ["video_asset", "video_metadata"], ["audio_peaks"]),
            ("Language/subtitle signal extraction", "Use speech, subtitle, or keyword signal when available without requiring manual event records.", ["video_asset"], ["language_signals"]),
            ("Highlight candidate generation", "Fuse frame, audio, language, and short-window event density into candidate windows.", ["frame_samples", "audio_peaks", "language_signals"], ["highlight_candidates"]),
            ("Multi-criteria scoring", "Rank candidates by motion, audio, language keywords, continuity, and user sensitivity settings.", ["highlight_candidates"], ["ranked_highlights"]),
            ("Clip export", "Export separate MP4 highlight clips or a cut manifest that can be rendered losslessly from the source video.", ["ranked_highlights", "game_video_file"], ["highlight_video_files", "clip_manifest"]),
            ("Settings UI", "Let the user tune minimum clip duration and sensitivity without requiring technical setup.", ["user_settings"], ["analysis_parameters"]),
        ]
        return {
            "features": [
                {
                    "id": f"F{index:03d}",
                    "name": name,
                    "description": description,
                    "priority": "Must" if index <= 8 else "Should",
                    "inputs": inputs,
                    "outputs": outputs,
                    "source_type": "explicit" if index in (1, 8, 9) else "inferred",
                }
                for index, (name, description, inputs, outputs) in enumerate(features, 1)
            ]
        }
    base_features = [
        ("Project intake", "Create a project from a raw natural-language request.", ["project_name", "raw_requirement"], ["project_id", "project_profile"]),
        ("Requirement understanding", "Extract business goal, users, scenarios, pain points, and boundaries.", ["raw_requirement"], ["requirement_spec"]),
        ("Input/output contract analysis", "Identify input sources, process steps, outputs, formats, consumers, unknowns, and source types.", ["raw_requirement", "requirement_spec"], ["io_contract"]),
        ("Gap confirmation", "Classify unknowns by Level 1/2/3 and block only unresolved Level 3 gaps.", ["io_contract"], ["gap_analysis"]),
        ("Feature decomposition", "Convert confirmed requirement contracts into feature modules.", ["requirement_spec", "io_contract"], ["feature_spec"]),
        ("Capability mapping", "Map each feature to concrete implementation capabilities.", ["feature_spec"], ["capability_map"]),
        ("Technology discovery", "Find candidate libraries or local catalog options for each capability.", ["capability_map"], ["tech_candidates"]),
        ("Technology decision", "Score candidates and choose library, custom, hybrid, or defer decisions.", ["tech_candidates"], ["tech_decisions"]),
        ("Blueprint generation", "Emit architecture, API, database, frontend, workflow, deployment, risks, and PRD artifacts.", ["feature_spec", "tech_decisions"], ["blueprint_artifacts"]),
        ("Task backlog", "Convert the blueprint into implementation tasks with dependencies and acceptance criteria.", ["blueprint_artifacts"], ["task_backlog"]),
    ]
    explicit_features = answers.get("core_features", "").strip()
    features = []
    for index, (name, description, inputs, outputs) in enumerate(base_features, 1):
        features.append(
            {
                "id": f"F{index:03d}",
                "name": name,
                "description": description,
                "priority": "Must" if index <= 8 else "Should",
                "inputs": inputs,
                "outputs": outputs,
                "source_type": "assumed",
            }
        )
    if explicit_features:
        features.append(
            {
                "id": f"F{len(features) + 1:03d}",
                "name": "User-specified capability",
                "description": explicit_features,
                "priority": "Must",
                "inputs": ["confirmed_requirement"],
                "outputs": ["implementation_scope_item"],
                "source_type": "explicit",
            }
        )
    return {"features": features}


CAPABILITY_RULES = {
    "Video intake": ["file_input", "local_video_preview", "input_validation"],
    "Video metadata extraction": ["video_metadata_probe", "duration_detection", "mime_type_validation"],
    "Frame signal extraction": ["frame_sampling", "motion_signal_detection", "timeline_windowing"],
    "Audio signal extraction": ["audio_peak_detection", "energy_timeline", "timeline_windowing"],
    "Language/subtitle signal extraction": ["keyword_signal_detection", "optional_ocr_or_transcript"],
    "Highlight candidate generation": ["signal_fusion", "candidate_window_generation"],
    "Multi-criteria scoring": ["weighted_scoring", "risk_analysis", "decision_explanation"],
    "Clip export": ["mp4_export", "clip_manifest_generation", "quality_preserving_cut"],
    "Settings UI": ["form_controls", "parameter_persistence", "local_artifact_storage"],
    "Project intake": ["project_state", "text_input", "local_artifact_storage"],
    "Requirement understanding": ["structured_ai_output", "schema_validation", "business_analysis"],
    "Input/output contract analysis": ["io_contract_modeling", "source_attribution", "confidence_scoring"],
    "Gap confirmation": ["gap_severity_rules", "user_confirmation_gate", "default_assumption_policy"],
    "Feature decomposition": ["feature_modeling", "priority_classification", "traceability"],
    "Capability mapping": ["capability_taxonomy", "feature_to_capability_mapping"],
    "Technology discovery": ["local_tech_catalog", "optional_web_search", "package_registry_lookup", "security_check"],
    "Technology decision": ["weighted_scoring", "risk_analysis", "decision_explanation"],
    "Blueprint generation": ["markdown_generation", "mermaid_generation", "openapi_generation", "sql_schema_generation"],
    "Task backlog": ["task_dependency_graph", "csv_export", "acceptance_criteria_generation"],
}


def build_capability_map(feature_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "capability_map": [
            {
                "feature": feature["name"],
                "capabilities": CAPABILITY_RULES.get(feature["name"], ["custom_business_logic"]),
            }
            for feature in feature_spec.get("features", [])
        ]
    }


def build_tech_candidates(capability_map: dict[str, Any]) -> dict[str, Any]:
    catalog = {
        "structured_ai_output": [("OpenAI Structured Outputs", "api", "Schema-constrained model output")],
        "schema_validation": [("jsonschema", "python", "Validate generated JSON artifacts")],
        "markdown_generation": [("custom Markdown renderer", "custom", "Generate PRD and readable summaries")],
        "mermaid_generation": [("Mermaid", "diagram", "Architecture and flow diagrams")],
        "openapi_generation": [("OpenAPI YAML", "spec", "API contract export")],
        "sql_schema_generation": [("SQL DDL", "spec", "Database schema export")],
        "csv_export": [("Python csv", "stdlib", "Task backlog CSV export")],
        "optional_web_search": [("official docs / package registries", "external", "Only when network is explicitly approved")],
    }
    rows = []
    for item in capability_map.get("capability_map", []):
        for capability in item.get("capabilities", []):
            candidates = catalog.get(capability, [("custom CGNK rule", "custom", "Deterministic local implementation")])
            rows.append(
                {
                    "capability": capability,
                    "feature": item.get("feature"),
                    "candidates": [
                        {
                            "name": name,
                            "ecosystem": ecosystem,
                            "use_for": use_for,
                            "latest_version": "not_checked_offline",
                            "fit_score": 0.82 if ecosystem != "external" else 0.7,
                            "maintenance_score": 0.8 if ecosystem in {"python", "stdlib", "spec", "diagram"} else 0.68,
                            "maturity_score": 0.78,
                            "security_score": 0.85 if ecosystem != "external" else 0.65,
                            "docs_score": 0.75,
                            "recommendation": "recommended",
                            "risk_points": ["Version freshness requires online verification before production use."],
                            "provenance": "local_catalog",
                        }
                        for name, ecosystem, use_for in candidates
                    ],
                }
            )
    return {"tech_candidates": rows}


def score_candidate(candidate: dict[str, Any]) -> float:
    return round(
        float(candidate.get("fit_score", 0)) * 0.35
        + float(candidate.get("maintenance_score", 0)) * 0.20
        + float(candidate.get("maturity_score", 0)) * 0.20
        + float(candidate.get("security_score", 0)) * 0.15
        + float(candidate.get("docs_score", 0)) * 0.10,
        3,
    )


def build_tech_decisions(tech_candidates: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    for row in tech_candidates.get("tech_candidates", []):
        candidates = row.get("candidates", [])
        if not candidates:
            continue
        selected = max(candidates, key=score_candidate)
        ecosystem = selected.get("ecosystem")
        if ecosystem in {"custom"}:
            decision_type = "custom"
        elif ecosystem in {"external"}:
            decision_type = "defer"
        elif ecosystem in {"api"}:
            decision_type = "hybrid"
        else:
            decision_type = "library"
        decisions.append(
            {
                "capability": row.get("capability"),
                "feature": row.get("feature"),
                "decision_type": decision_type,
                "selected_solution": selected.get("name"),
                "weighted_score": score_candidate(selected),
                "reason": f"Selected for {selected.get('use_for')} with local-catalog evidence.",
                "alternatives": [item.get("name") for item in candidates if item is not selected],
                "risks": selected.get("risk_points", []),
                "implementation_note": "Re-check package versions and security metadata when network access is explicitly allowed.",
            }
        )
    return {"tech_decisions": decisions}


def build_architecture_mmd(requirement: str = "") -> str:
    if wants_game_video_highlight(requirement):
        return """flowchart TD
  U[User] --> IN[VideoInputAgent]
  IN --> META[VideoMetadataAgent]
  META --> FRAME[FrameSignalAgent]
  META --> AUDIO[AudioSignalAgent]
  META --> LANG[SpeechOrSubtitleSignalAgent]
  FRAME --> CAND[HighlightCandidateAgent]
  AUDIO --> CAND
  LANG --> CAND
  CAND --> SCORE[MultiCriteriaScoringAgent]
  SCORE --> BOUND[ClipBoundaryAgent]
  BOUND --> EXPORT[ExportAgent]
  EXPORT --> MP4[MP4 Highlight Clips]
  EXPORT --> MANIFEST[Clip Manifest]
  SCORE --> REPORT[Analysis Report]
  MP4 --> REVIEW[Review UI]
  MANIFEST --> REVIEW
  REPORT --> REVIEW
"""
    return """flowchart TD
  U[User] --> ORCH[CGNK Orchestrator]
  ORCH --> RA[RequirementAgent]
  RA --> IO[IOContractAgent]
  IO --> GA[GapAgent]
  GA --> FA[FeatureAgent]
  FA --> CA[CapabilityAgent]
  CA --> TSA[TechSearchAgent]
  TSA --> TDA[TechDecisionAgent]
  TDA --> BA[BlueprintAgent]
  BA --> TA[TaskAgent]
  TA --> REV[ReviewAgent]
  REV --> ART[Blueprint Artifacts]
  ART --> GEN[Existing CGNK Project Generation]
"""


def build_api_yaml(requirement: str = "") -> str:
    if wants_game_video_highlight(requirement):
        return """openapi: 3.1.0
info:
  title: Game Video Highlight Finder API
  version: 1.0.0
paths:
  /api/videos:
    post:
      summary: Register one local game video for analysis
  /api/videos/{video_id}/analyze:
    post:
      summary: Run multi-signal highlight detection with duration and sensitivity settings
  /api/videos/{video_id}/highlights:
    get:
      summary: List ranked highlight candidates and scoring explanations
  /api/videos/{video_id}/exports:
    post:
      summary: Export selected highlights as MP4 clips or a cut manifest
"""
    return """openapi: 3.1.0
info:
  title: CGNK Requirement Blueprint API
  version: 1.0.0
paths:
  /api/projects:
    post:
      summary: Create a project
  /api/projects/{project_id}/requirements:
    post:
      summary: Submit raw requirement
  /api/projects/{project_id}/analyze-io:
    post:
      summary: Run IOContractAgent
  /api/projects/{project_id}/generate-blueprint:
    post:
      summary: Generate blueprint artifacts
  /api/projects/{project_id}/artifacts:
    get:
      summary: List generated artifacts
"""


def build_db_schema_sql(requirement: str = "") -> str:
    if wants_game_video_highlight(requirement):
        return """CREATE TABLE videos (
  id TEXT PRIMARY KEY,
  file_name TEXT NOT NULL,
  duration_seconds REAL,
  mime_type TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE analysis_runs (
  id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES videos(id),
  min_highlight_duration REAL NOT NULL,
  sensitivity REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE highlight_candidates (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES analysis_runs(id),
  start_seconds REAL NOT NULL,
  end_seconds REAL NOT NULL,
  score REAL NOT NULL,
  visual_score REAL,
  audio_score REAL,
  language_score REAL,
  continuity_score REAL,
  explanation TEXT
);

CREATE TABLE exports (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES analysis_runs(id),
  candidate_id TEXT REFERENCES highlight_candidates(id),
  path TEXT NOT NULL,
  format TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""
    return """CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  project_type TEXT,
  status TEXT NOT NULL DEFAULT 'created',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE requirements (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  raw_text TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  agent_name TEXT NOT NULL,
  input_json TEXT,
  output_json TEXT,
  status TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  artifact_type TEXT NOT NULL,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def build_frontend_pages(requirement: str = "") -> dict[str, Any]:
    if wants_game_video_highlight(requirement):
        return {
            "pages": [
                {"id": "video_intake", "title": "Video Intake", "purpose": "Select one local game video and validate that it can be previewed."},
                {"id": "analysis_settings", "title": "Analysis Settings", "purpose": "Set minimum highlight duration, sensitivity, and output format."},
                {"id": "signal_timeline", "title": "Signal Timeline", "purpose": "Show visual, audio, language, and continuity signals across the video."},
                {"id": "highlight_review", "title": "Highlight Review", "purpose": "Review ranked candidates with score explanations and clip boundaries."},
                {"id": "export_queue", "title": "Export Queue", "purpose": "Export selected candidates as MP4 clips and save a clip manifest."},
            ]
        }
    return {
        "pages": [
            {"id": "requirement_input", "title": "Requirement Input", "purpose": "Collect raw text, optional documents, and output goals."},
            {"id": "io_contract_review", "title": "I/O Contract Review", "purpose": "Review inputs, process steps, outputs, unknowns, source types, and confidence."},
            {"id": "gap_confirmation", "title": "Gap Confirmation", "purpose": "Resolve Level 3 gaps and optionally confirm Level 2 defaults."},
            {"id": "feature_modules", "title": "Feature Modules", "purpose": "Edit generated features, priorities, inputs, and outputs."},
            {"id": "tech_decisions", "title": "Tech Decisions", "purpose": "Compare candidates, scores, risks, and selected solutions."},
            {"id": "blueprint_preview", "title": "Blueprint Preview", "purpose": "Inspect architecture, API, database, page, deployment, and risk artifacts."},
            {"id": "task_backlog", "title": "Task Backlog", "purpose": "Edit implementation tasks, dependencies, acceptance criteria, and CSV export."},
        ]
    }


def build_task_backlog(feature_spec: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = []
    previous = ""
    for index, feature in enumerate(feature_spec.get("features", []), 1):
        task_id = f"T{index:03d}"
        tasks.append(
            {
                "id": task_id,
                "title": f"Implement {feature['name']}",
                "module": feature["name"].lower().replace(" ", "_"),
                "priority": feature.get("priority", "Should"),
                "depends_on": [previous] if previous else [],
                "acceptance_criteria": [
                    "Inputs and outputs are explicit.",
                    "Generated artifact validates as structured JSON, Markdown, Mermaid, YAML, SQL, or CSV as applicable.",
                    "Traceability to requirement_spec or io_contract is preserved.",
                ],
                "output": feature.get("outputs", []),
            }
        )
        previous = task_id
    return tasks


def task_backlog_csv(tasks: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["id", "title", "module", "priority", "depends_on", "acceptance_criteria", "output"])
    writer.writeheader()
    for task in tasks:
        writer.writerow(
            {
                "id": task["id"],
                "title": task["title"],
                "module": task["module"],
                "priority": task["priority"],
                "depends_on": ";".join(task.get("depends_on", [])),
                "acceptance_criteria": " | ".join(task.get("acceptance_criteria", [])),
                "output": ";".join(task.get("output", [])),
            }
        )
    return buf.getvalue()


def build_prd(requirement: str, requirement_spec: dict[str, Any], feature_spec: dict[str, Any], tech_decisions: dict[str, Any]) -> str:
    features = "\n".join(f"- {item['name']}: {item['description']}" for item in feature_spec.get("features", []))
    decisions = "\n".join(f"- {item['capability']}: {item['selected_solution']} ({item['decision_type']})" for item in tech_decisions.get("tech_decisions", [])[:12])
    users = ", ".join(str(item) for item in requirement_spec.get("target_users", {}).get("value", []))
    return f"""# Requirement Blueprint PRD

## Raw Requirement

{clean_text(requirement)}

## Target Users

{users}

## Core Features

{features}

## Technology Decisions

{decisions}

## Acceptance

- The blueprint includes requirement, I/O, feature, capability, technology, architecture, API, database, frontend, task, and review artifacts.
- Level 3 gaps must be resolved before treating the blueprint as final.
- External technology freshness checks require explicit network approval.
"""


def build_review_report(blueprint_parts: dict[str, Any]) -> dict[str, Any]:
    issues = []
    gap_analysis = blueprint_parts["gap_analysis"]
    for gap in gap_analysis.get("gap_items", []):
        if gap.get("severity") == "Level 3" and gap.get("status") != "resolved":
            issues.append(
                {
                    "stage": "gap_analysis",
                    "problem": gap.get("question"),
                    "severity": "high",
                    "send_back_to": "GapAgent",
                }
            )
    if not blueprint_parts["tech_decisions"].get("tech_decisions"):
        issues.append(
            {
                "stage": "tech_decision",
                "problem": "No technology decisions were generated.",
                "severity": "high",
                "send_back_to": "TechDecisionAgent",
            }
        )
    return {"passed": not issues, "issues": issues}


def build_requirement_blueprint(
    raw_requirement: str,
    answers: list[dict[str, str]] | None = None,
    *,
    assume_defaults: bool = True,
) -> dict[str, Any]:
    mapped_answers = answer_map(answers)
    requirement_spec = build_requirement_spec(raw_requirement, mapped_answers)
    io_contract = build_io_contract(raw_requirement, requirement_spec, mapped_answers)
    gap_analysis = build_gap_analysis(raw_requirement, mapped_answers, assume_defaults)
    feature_spec = build_feature_spec(raw_requirement, mapped_answers)
    capability_map = build_capability_map(feature_spec)
    tech_candidates = build_tech_candidates(capability_map)
    tech_decisions = build_tech_decisions(tech_candidates)
    frontend_pages = build_frontend_pages(raw_requirement)
    tasks = build_task_backlog(feature_spec)
    parts = {
        "requirement_spec": requirement_spec,
        "io_contract": io_contract,
        "gap_analysis": gap_analysis,
        "feature_spec": feature_spec,
        "capability_map": capability_map,
        "tech_candidates": tech_candidates,
        "tech_decisions": tech_decisions,
        "frontend_pages": frontend_pages,
        "task_backlog": {"tasks": tasks},
    }
    review_report = build_review_report(parts)
    return {
        "kind": "RequirementBlueprint",
        "created_at": now(),
        "raw_requirement": raw_requirement,
        "agent_sequence": AGENT_SEQUENCE,
        "status": "ready" if review_report["passed"] and gap_analysis["can_continue"] else "needs_clarification",
        "requirement_spec": requirement_spec,
        "io_contract": io_contract,
        "gap_analysis": gap_analysis,
        "feature_spec": feature_spec,
        "capability_map": capability_map,
        "tech_candidates": tech_candidates,
        "tech_decisions": tech_decisions,
        "architecture_mmd": build_architecture_mmd(raw_requirement),
        "api_openapi_yaml": build_api_yaml(raw_requirement),
        "db_schema_sql": build_db_schema_sql(raw_requirement),
        "frontend_pages": frontend_pages,
        "task_backlog": {"tasks": tasks},
        "task_backlog_csv": task_backlog_csv(tasks),
        "prd_md": build_prd(raw_requirement, requirement_spec, feature_spec, tech_decisions),
        "review_report": review_report,
    }


def export_requirement_blueprint_files(blueprint: dict[str, Any]) -> dict[str, str]:
    json_parts = [
        "requirement_spec",
        "io_contract",
        "gap_analysis",
        "feature_spec",
        "capability_map",
        "tech_candidates",
        "tech_decisions",
        "frontend_pages",
    ]
    files = {f"{name}.json": json.dumps(blueprint.get(name, {}), ensure_ascii=False, indent=2) + "\n" for name in json_parts}
    files.update(
        {
            "architecture.mmd": str(blueprint.get("architecture_mmd", "")),
            "api.openapi.yaml": str(blueprint.get("api_openapi_yaml", "")),
            "db_schema.sql": str(blueprint.get("db_schema_sql", "")),
            "task_backlog.csv": str(blueprint.get("task_backlog_csv", "")),
            "prd.md": str(blueprint.get("prd_md", "")),
            "review_report.json": json.dumps(blueprint.get("review_report", {}), ensure_ascii=False, indent=2) + "\n",
        }
    )
    return files


def write_requirement_blueprint_outputs(base_dir: pathlib.Path, blueprint: dict[str, Any]) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for rel, text in export_requirement_blueprint_files(blueprint).items():
        path = base_dir / rel
        write_text(path, text)
        outputs[rel] = str(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--outputs-dir", default="")
    parser.add_argument("--assume-defaults", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    blueprint = build_requirement_blueprint(args.requirement, assume_defaults=bool(args.assume_defaults))
    if args.out:
        write_json(pathlib.Path(args.out).resolve(), blueprint)
    if args.outputs_dir:
        write_requirement_blueprint_outputs(pathlib.Path(args.outputs_dir).resolve(), blueprint)
    if args.json:
        print(json.dumps(blueprint, ensure_ascii=False, indent=2))
    else:
        print(f"REQUIREMENT_BLUEPRINT: {blueprint['status'].upper()}")
        if args.out:
            print(f"out={pathlib.Path(args.out).resolve()}")
        if args.outputs_dir:
            print(f"outputs_dir={pathlib.Path(args.outputs_dir).resolve()}")
    return 0 if blueprint["status"] in {"ready", "needs_clarification"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
