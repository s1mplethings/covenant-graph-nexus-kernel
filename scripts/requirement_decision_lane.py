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
    if any(token in lowered for token in ("video", "media", "clip", "audio", "视频", "音频", "素材")):
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


def _video_requirement() -> dict[str, Any]:
    return _candidate(
        candidate_id="local_video_material_workbench_requirement",
        name="Local video material processing workbench",
        summary="A local-first workbench for ingesting video, extracting or simulating audio, chunking/transcribing, analyzing segments, selecting clips, and exporting reviewable artifacts.",
        target_user="Creators or operators who need repeatable local media processing.",
        core_problem="Raw media work becomes untraceable and hard to evaluate when it is reduced to a single preview.",
        product_shape="Desktop/web GUI plus CLI over a shared orchestration core.",
        mvp_features=["Local media import", "Pipeline run view", "Segment review", "Clip selection", "Artifact export", "Honest degraded mode"],
        non_goals=["Cloud rendering farm", "Guaranteed real speech recognition without configured model", "Public media publishing"],
        core_workflow=["import media", "extract audio", "chunk input", "transcribe or degrade honestly", "score segments", "select clips", "export manifests"],
        pages=["Import", "Pipeline", "Segments", "Review", "Exports", "Settings"],
        modules=["orchestrator", "stages", "artifact_store", "cli", "gui", "degraded_runtime", "tests"],
        stages=["ingest_video", "extract_audio", "chunk_audio", "transcribe_audio", "analyze_segments", "select_segments", "render_clips", "export_results"],
        artifacts=["stage_plan.json", "media_manifest.json", "audio_chunk_manifest.json", "transcript_merged.json", "segment_analysis.json", "selected_segments.json", "clip_manifest.json", "export_results.json"],
        match="It turns the rough video-tool goal into a concrete local product with testable artifacts.",
        wrong="If the customer only wanted a tiny converter, this is larger than needed.",
        complexity_level="production_scale",
        customer_value_score=94,
        clarity_score=92,
        local_first_feasibility=84,
        delivery_feasibility=82,
        testability_score=86,
        implementation_risk="medium",
        demo_degradation_risk="low",
        fake_pass_risk="low",
        acceptance_summary="A run creates stage artifacts, GUI/CLI share the same core, and missing models are reported as degraded instead of success.",
    )


def _team_requirement() -> dict[str, Any]:
    return _candidate(
        candidate_id="indie_team_operating_console_requirement",
        name="Independent team operating console",
        summary="A local team management product for milestones, tasks, assets, decisions, risks, playtest notes, and release-readiness evidence.",
        target_user="Small independent teams that need lightweight operational discipline.",
        core_problem="Team context gets scattered across task lists, asset folders, and decisions with no shared acceptance view.",
        product_shape="Project dashboard with CLI import/export and structured local storage.",
        mvp_features=["Milestone board", "Decision log", "Risk register", "Asset/task links", "Acceptance checklist", "Exportable status report"],
        non_goals=["Full HR/payroll", "Real-time multiplayer collaboration", "Enterprise permission system"],
        core_workflow=["create project", "define milestone", "link tasks and assets", "record decisions", "review risks", "export release report"],
        pages=["Dashboard", "Milestones", "Tasks", "Assets", "Decisions", "Risks", "Release"],
        modules=["orchestrator", "stages", "storage", "cli", "gui", "reporting", "tests"],
        stages=["load_workspace", "plan_milestones", "link_assets", "record_decisions", "assess_risks", "review_acceptance", "export_status"],
        artifacts=["workspace_manifest.json", "milestone_plan.json", "asset_links.json", "decision_log.json", "risk_register.json", "acceptance_status.json", "release_report.json"],
        match="It interprets a team-tool goal as a decision and delivery coordination product.",
        wrong="If the customer wants only a generic kanban, this has more product structure than needed.",
        complexity_level="complex",
        customer_value_score=84,
        clarity_score=82,
        local_first_feasibility=90,
        delivery_feasibility=86,
        testability_score=88,
        implementation_risk="low",
        demo_degradation_risk="medium",
        fake_pass_risk="low",
        acceptance_summary="The product must prove that team artifacts, decisions, risks, and release status are connected and exportable.",
    )


def _research_requirement() -> dict[str, Any]:
    return _candidate(
        candidate_id="local_research_workspace_requirement",
        name="Local research and source synthesis workspace",
        summary="A local research workspace for importing documents, extracting notes, linking source evidence, clustering topics, and producing traceable briefs.",
        target_user="Researchers or operators organizing local materials.",
        core_problem="Research notes lose provenance and cannot be reviewed when reduced to a static notes page.",
        product_shape="Local knowledge workbench with document intake, evidence graph, synthesis board, CLI batch run, and GUI review.",
        mvp_features=["Document import", "Metadata extraction", "Evidence notes", "Topic clustering", "Brief generation", "Source traceability"],
        non_goals=["Cloud knowledge base sync", "Guaranteed OCR/model extraction without configured dependency", "Legal/medical claims verification"],
        core_workflow=["import sources", "extract metadata", "create notes", "cluster topics", "draft brief", "export evidence pack"],
        pages=["Sources", "Notes", "Topics", "Evidence", "Brief", "Exports"],
        modules=["orchestrator", "stages", "source_store", "cli", "gui", "synthesis", "tests"],
        stages=["load_sources", "extract_metadata", "create_notes", "cluster_topics", "link_evidence", "draft_brief", "export_pack"],
        artifacts=["source_manifest.json", "metadata_index.json", "notes.json", "topic_clusters.json", "evidence_links.json", "brief_draft.json", "export_manifest.json"],
        match="It makes a vague research-workbench goal concrete and locally testable.",
        wrong="If the customer needs live web research, local-first mode is only the first version.",
        complexity_level="complex",
        customer_value_score=86,
        clarity_score=84,
        local_first_feasibility=92,
        delivery_feasibility=84,
        testability_score=88,
        implementation_risk="low",
        demo_degradation_risk="low",
        fake_pass_risk="low",
        acceptance_summary="The output must preserve source-to-brief traceability and report degraded extraction honestly.",
    )


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
    lowered = raw_goal.lower()
    candidates: list[dict[str, Any]] = []
    if any(token in lowered for token in ("video", "media", "clip", "audio", "视频", "音频", "素材")):
        candidates.append(_video_requirement())
    if any(token in lowered for token in ("game", "studio", "team", "indie", "独立游戏", "团队", "管理")):
        candidates.append(_team_requirement())
    if any(token in lowered for token in ("research", "资料", "整理", "knowledge", "文档", "工作台")):
        candidates.append(_research_requirement())
    for candidate in (_video_requirement(), _team_requirement(), _research_requirement(), _cloud_requirement(), _small_demo_requirement()):
        if not any(existing["id"] == candidate["id"] for existing in candidates):
            candidates.append(candidate)
    return {"customer_goal": raw_goal, "generated_at": now(), "candidates": candidates[:5]}


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
    }


def build_acceptance_contract(selected: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": "requirement_acceptance_contract_v1",
        "selected_requirement_id": selected.get("selected_requirement_id", ""),
        "success_definition": selected.get("acceptance_summary", ""),
        "required_planning_docs": ["product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md"],
        "required_requirement_artifacts": REQUIREMENT_ARTIFACTS,
        "required_product_outputs": [],
        "required_delivery_evidence": ["README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md", "run_dir"],
        "implementation_delivery_evidence": ["final_project_bundle.zip", "screenshot"],
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
    paths = {
        "customer_goal_brief": str(base / "customer_goal_brief.md"),
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
    interpretations = generate_need_interpretations(raw_goal, context)
    candidates = generate_candidate_requirements(raw_goal, interpretations, context)
    scorecard = score_candidate_requirements(candidates, context)
    selected = select_requirement(candidates, scorecard, context)
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
