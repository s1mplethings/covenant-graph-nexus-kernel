#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
from typing import Any


MANIFEST_KIND = "AgentGeneratedPipelineManifest"
MANIFEST_VERSION = 1
MAX_ROLES = 8
MAX_STEPS = 12
ALLOWED_STEP_TYPES = {"agent_turn", "use_skill", "run_command", "package_project", "update_whiteboard"}
REQUIRED_STAGES = [
    "product_plan",
    "technical_plan",
    "build",
    "test",
    "evidence_review",
    "review",
    "package",
]
ALLOWED_STAGES = set(REQUIRED_STAGES)
ALLOWED_ACTION_TYPES = {
    "write_file",
    "read_file",
    "list_files",
    "run_command",
    "capture_screenshot",
    "package_project",
    "search_skills",
    "use_skill",
    "propose_skill",
    "final_message",
}
FORBIDDEN_LEGACY_PATTERNS = (
    "generate_project.py",
    "run_local_pipeline",
    "simulator",
)


def _slug(raw: Any, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(raw or "").strip().lower()).strip("_")
    return text[:48] or fallback


def _strings(value: Any, *, limit: int = 16) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:500] for item in value[:limit] if str(item).strip()]


def _stage_values(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    stages: list[str] = []
    for item in raw:
        stage = str(item or "").strip()
        if stage and stage not in stages:
            stages.append(stage)
    return stages


def _project_goal(whiteboard: dict[str, Any]) -> str:
    for key in ("project_summary", "summary", "goal"):
        text = str(whiteboard.get(key, "")).strip()
        if text:
            return text[:2000]
    facts = _strings(whiteboard.get("known_facts", []), limit=3)
    if facts:
        return "\n".join(facts)[:2000]
    return "Generate the first usable version of the project described in the session."


def _normalized_cfo_contract(candidate: Any, whiteboard: dict[str, Any]) -> dict[str, Any]:
    defaults = default_minimal_pipeline_manifest(whiteboard)["cfo_contract"]
    raw = candidate if isinstance(candidate, dict) else {}
    support = raw.get("support_artifacts") if isinstance(raw.get("support_artifacts"), dict) else {}
    default_support = defaults["support_artifacts"]
    return {
        "authority": str(raw.get("authority") or defaults["authority"]).strip()[:500],
        "planning_artifact": str(raw.get("planning_artifact") or defaults["planning_artifact"]).strip()[:120],
        "review_artifact": str(raw.get("review_artifact") or defaults["review_artifact"]).strip()[:120],
        "support_artifacts": {
            "context_db": str(support.get("context_db") or default_support["context_db"]).strip()[:120],
            "risk_register": str(support.get("risk_register") or default_support["risk_register"]).strip()[:120],
            "codex_capability_brief": str(
                support.get("codex_capability_brief")
                or default_support["codex_capability_brief"]
            ).strip()[:120],
        },
        "support_agent_rule": str(raw.get("support_agent_rule") or defaults["support_agent_rule"]).strip()[:500],
        "worker_handoff_rule": str(raw.get("worker_handoff_rule") or defaults["worker_handoff_rule"]).strip()[:500],
        "evidence_rule": str(raw.get("evidence_rule") or defaults["evidence_rule"]).strip()[:500],
    }


def default_minimal_pipeline_manifest(whiteboard: dict[str, Any] | None) -> dict[str, Any]:
    board = whiteboard if isinstance(whiteboard, dict) else {}
    goal = _project_goal(board)
    return {
        "kind": MANIFEST_KIND,
        "version": MANIFEST_VERSION,
        "project_goal": goal,
        "source": "planner_agent",
        "cfo_contract": {
            "authority": "cfo owns module planning, handoff order, acceptance interpretation, evidence review, and final delivery readiness",
            "planning_artifact": "MODULE_PIPELINE.md",
            "review_artifact": "DELIVERY_NOTES.md",
            "support_artifacts": {
                "context_db": "CFO_CONTEXT_DB.json",
                "risk_register": "CFO_RISK_REGISTER.md",
                "codex_capability_brief": "CODEX_CAPABILITY_BRIEF.json",
            },
            "support_agent_rule": "support agents maintain factual context and risk artifacts for cfo and workers; they do not own scope, final route, or delivery readiness",
            "worker_handoff_rule": "each worker must read MODULE_PIPELINE.md, update only its assigned project area, and leave a concise handoff note",
            "evidence_rule": "cfo_review must compare project files, tests, previews, and packaging evidence against whiteboard acceptance criteria before delivery",
        },
        "roles": [
            {
                "id": "cfo",
                "name": "CFO",
                "purpose": "main coordinating agent that turns the whiteboard into a modular execution plan, assigns worker agents, controls scope, reviews evidence, and decides delivery readiness",
            },
            {
                "id": "foundation",
                "name": "Foundation Agent",
                "purpose": "create project structure, README, dependency/config files, and shared contracts exactly from the CFO module plan and support artifacts",
            },
            {
                "id": "context_librarian",
                "name": "CFO Context Librarian",
                "purpose": "maintain CFO_CONTEXT_DB.json as a factual project context database from whiteboard, session events, attachments, assumptions, acceptance criteria, module dependencies, and handoff references",
            },
            {
                "id": "codex_capability_supervisor",
                "name": "Codex Capability Supervisor",
                "purpose": "operate above librarian context when an external Codex handoff is explicitly requested; diagnose bounded capability gaps with tools and return a validated advisory brief for CFO and workers without owning generation, formal evidence, packaging, or delivery",
            },
            {
                "id": "risk_reviewer",
                "name": "CFO Risk Reviewer",
                "purpose": "maintain CFO_RISK_REGISTER.md with implementation risks, missing evidence, dependency concerns, user-visible quality risks, and recommended checks for CFO review",
            },
            {
                "id": "backend",
                "name": "Backend Agent",
                "purpose": "implement service, data, integration, generation, and non-UI logic assigned by the CFO module plan",
            },
            {
                "id": "frontend",
                "name": "Frontend Agent",
                "purpose": "implement user-facing screens, interaction, visual preview, and static assets assigned by the CFO module plan",
            },
            {
                "id": "qa",
                "name": "QA Agent",
                "purpose": "run checks, inspect generated files, repair assigned failures, and document evidence and remaining limits for CFO review",
            },
        ],
        "shared_whiteboard_keys": [
            "project_summary",
            "frontend_plan",
            "backend_plan",
            "data_model",
            "first_version_scope",
            "first_version_plan",
            "default_assumptions",
            "assumptions",
            "user_rules",
            "acceptance",
            "acceptance_criteria",
            "change_requests",
            "delivery_requirements",
            "critical_questions",
            "capability_strategy",
            "capability_research_targets",
            "local_image_model_discovery",
            "codex_capability_supervision",
        ],
        "steps": [
            {
                "id": "cfo_pipeline",
                "type": "agent_turn",
                "stage": ["product_plan", "technical_plan"],
                "role": "cfo",
                "goal": "write PRODUCT_PLAN.md and OUTPUT_CONTRACT.md with user goal, first-version scope, default assumptions, non-goals, delivery format, and acceptance criteria; write TECHNICAL_PLAN.md and BUILD_PLAN.md with technical route, file structure, data flow, run method, test plan, risks, and dependencies; also update MODULE_PIPELINE.md for worker handoff order and evidence targets",
                "allowed_actions": [
                    "write_file",
                    "read_file",
                    "list_files",
                    "use_skill",
                    "search_skills",
                ],
            },
            {
                "id": "context_support",
                "type": "agent_turn",
                "stage": "technical_plan",
                "role": "context_librarian",
                "goal": "read MODULE_PIPELINE.md, whiteboard/session context, and available project inputs; write CFO_CONTEXT_DB.json as a compact factual database of project goal, user rules, acceptance criteria, delivery requirements, attachments, assumptions, module map, dependencies, handoff references, and open facts for CFO and workers",
                "allowed_actions": ["write_file", "read_file", "list_files"],
            },
            {
                "id": "risk_support",
                "type": "agent_turn",
                "stage": "technical_plan",
                "role": "risk_reviewer",
                "goal": "read MODULE_PIPELINE.md and CFO_CONTEXT_DB.json; write CFO_RISK_REGISTER.md with risks, default assumptions to verify, likely failure modes, user-visible quality checks, required evidence, and repair priorities for CFO review",
                "allowed_actions": ["write_file", "read_file", "list_files"],
            },
            {
                "id": "build",
                "type": "agent_turn",
                "stage": "build",
                "role": "backend",
                "goal": "read PRODUCT_PLAN.md, OUTPUT_CONTRACT.md, TECHNICAL_PLAN.md, BUILD_PLAN.md, MODULE_PIPELINE.md, CFO_CONTEXT_DB.json, optional CODEX_CAPABILITY_BRIEF.json, CFO_RISK_REGISTER.md, and existing handoffs when present; generate a real runnable project, not only documents; must write README.md, app.py or main.py, requirements.txt or pyproject.toml, source code, tests, and required visual evidence such as UI screenshot plus generated background/立绘 images when requested; do not package",
                "allowed_actions": ["write_file", "read_file", "list_files", "run_command", "use_skill", "search_skills"],
            },
            {
                "id": "qa",
                "type": "agent_turn",
                "stage": "test",
                "role": "qa",
                "goal": "must write TEST_REPORT.md; must run at least one real feasible check command against the generated project; TEST_REPORT.md must include commands_run, results, failures, repairs, and remaining_warnings; if TEST_REPORT.md contains NO TEST EXECUTED the step is not complete and must be repaired before package",
                "allowed_actions": ["write_file", "read_file", "list_files", "run_command", "capture_screenshot", "use_skill", "search_skills"],
            },
            {
                "id": "evidence_review",
                "type": "agent_turn",
                "stage": "evidence_review",
                "role": "qa",
                "goal": (
                    "整理用户可判断的中间证据。必须读取 TEST_REPORT.md，列出测试代码、测试命令、样例输入、截图/视频/预览文件。"
                    "如果没有真实输入或视频，必须明确说明缺少什么。写 EVIDENCE_REVIEW.md，且必须包含字段: "
                    "test_code_files, test_commands, sample_inputs, screenshots, videos, preview_files, "
                    "what_user_should_check, missing_real_evidence, next_recommended_action"
                ),
                "allowed_actions": [
                    "write_file",
                    "read_file",
                    "list_files",
                    "run_command",
                    "capture_screenshot",
                    "search_skills",
                    "use_skill",
                ],
            },
            {
                "id": "cfo_review",
                "type": "agent_turn",
                "stage": "review",
                "role": "cfo",
                "goal": "must read TEST_REPORT.md; must write DELIVERY_NOTES.md containing delivery_status: PASS / WARNING / PARTIAL, tests_executed, evidence_found, evidence_missing, known_limits, and revision_entry; if TEST_REPORT.md is missing, do not write PASS",
                "allowed_actions": ["write_file", "read_file", "list_files", "run_command", "capture_screenshot", "use_skill", "search_skills"],
            },
            {
                "id": "package",
                "type": "package_project",
                "stage": "package",
                "goal": "call package_project to create final_project_bundle.zip and delivery_manifest.json",
            },
        ],
        "limits": {"max_agent_turns_per_step": 4, "max_total_steps": 10, "allow_dynamic_new_steps": False},
    }


def _contains_forbidden_legacy(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    return any(pattern in text for pattern in FORBIDDEN_LEGACY_PATTERNS)


def _step_calls_forbidden_legacy(step: dict[str, Any]) -> bool:
    executable_fields = {
        "type": step.get("type"),
        "command": step.get("command"),
        "action": step.get("action"),
        "skill": step.get("skill"),
        "name": step.get("name"),
    }
    return _contains_forbidden_legacy(executable_fields)


def validate_required_stages(manifest: Any) -> tuple[bool, list[str]]:
    if not isinstance(manifest, dict):
        return False, list(REQUIRED_STAGES)
    steps = manifest.get("steps")
    if not isinstance(steps, list) or not steps:
        return False, list(REQUIRED_STAGES)

    covered: set[str] = set()
    first_index: dict[str, int] = {}
    invalid: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        stages = _stage_values(step.get("stage"))
        for stage in stages:
            if stage not in ALLOWED_STAGES:
                invalid.append(stage)
                continue
            covered.add(stage)
            first_index.setdefault(stage, index)

    missing = [stage for stage in REQUIRED_STAGES if stage not in covered]
    issues = list(missing)
    if "package" in first_index:
        package_index = first_index["package"]
        for stage in ("test", "evidence_review", "review"):
            if stage in first_index and package_index < first_index[stage]:
                issues.append(f"package_before_{stage}")
    if "evidence_review" in first_index and "test" in first_index and first_index["evidence_review"] < first_index["test"]:
        issues.append("evidence_review_before_test")
    if "review" in first_index and "evidence_review" in first_index and first_index["review"] < first_index["evidence_review"]:
        issues.append("review_before_evidence_review")
    if invalid:
        issues.extend(f"invalid_stage:{stage}" for stage in invalid)
    return not issues, issues


def validate_pipeline_manifest(manifest: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return False, ["manifest must be a JSON object"]
    if manifest.get("kind") != MANIFEST_KIND:
        errors.append(f"kind must be {MANIFEST_KIND}")
    if manifest.get("version") != MANIFEST_VERSION:
        errors.append(f"version must be {MANIFEST_VERSION}")
    roles = manifest.get("roles")
    if not isinstance(roles, list) or not roles:
        errors.append("roles must be a non-empty list")
        roles = []
    if len(roles) > MAX_ROLES:
        errors.append(f"roles must contain at most {MAX_ROLES} items")
    role_ids: set[str] = set()
    for index, role in enumerate(roles):
        if not isinstance(role, dict):
            errors.append(f"roles[{index}] must be an object")
            continue
        role_id = str(role.get("id", "")).strip()
        if not role_id:
            errors.append(f"roles[{index}].id is required")
        if role_id in role_ids:
            errors.append(f"duplicate role id: {role_id}")
        role_ids.add(role_id)
        if not str(role.get("name", "")).strip():
            errors.append(f"roles[{index}].name is required")
        if not str(role.get("purpose", "")).strip():
            errors.append(f"roles[{index}].purpose is required")

    steps = manifest.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty list")
        steps = []
    if len(steps) > MAX_STEPS:
        errors.append(f"steps must contain at most {MAX_STEPS} items")
    step_ids: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"steps[{index}] must be an object")
            continue
        step_id = str(step.get("id", "")).strip()
        step_type = str(step.get("type", "")).strip()
        if not step_id:
            errors.append(f"steps[{index}].id is required")
        if step_id in step_ids:
            errors.append(f"duplicate step id: {step_id}")
        step_ids.add(step_id)
        if step_type not in ALLOWED_STEP_TYPES:
            errors.append(f"steps[{index}].type is not allowed: {step_type}")
        stages = _stage_values(step.get("stage"))
        if not stages:
            errors.append(f"steps[{index}].stage is required")
        for stage in stages:
            if stage not in ALLOWED_STAGES:
                errors.append(f"steps[{index}].stage is not allowed: {stage}")
        if _step_calls_forbidden_legacy(step):
            errors.append(f"steps[{index}] must not call legacy generation paths")
        if step_type == "agent_turn":
            role_id = str(step.get("role", "")).strip()
            if role_id not in role_ids:
                errors.append(f"steps[{index}].role must reference a role id")
            allowed_actions = step.get("allowed_actions")
            if not isinstance(allowed_actions, list) or not allowed_actions:
                errors.append(f"steps[{index}].allowed_actions must be a non-empty list")
            else:
                for action in allowed_actions:
                    if str(action) not in ALLOWED_ACTION_TYPES:
                        errors.append(f"steps[{index}] has unsupported allowed action: {action}")
        if step_type in {"run_command", "use_skill"} and not (step.get("action") or step.get("command") or step.get("skill") or step.get("name")):
            errors.append(f"steps[{index}] must include executable step details")
    limits = manifest.get("limits", {})
    if limits is not None and not isinstance(limits, dict):
        errors.append("limits must be an object")
    stage_ok, stage_errors = validate_required_stages(manifest)
    if not stage_ok:
        errors.extend(f"required stage missing or invalid: {item}" for item in stage_errors)
    return not errors, errors


def normalize_pipeline_manifest(manifest: Any, whiteboard: dict[str, Any] | None) -> dict[str, Any]:
    board = whiteboard if isinstance(whiteboard, dict) else {}
    candidate = manifest if isinstance(manifest, dict) else {}
    normalized = {
        "kind": candidate.get("kind") or MANIFEST_KIND,
        "version": candidate.get("version") or MANIFEST_VERSION,
        "project_goal": str(candidate.get("project_goal") or _project_goal(board)).strip()[:2000],
        "source": str(candidate.get("source") or "planner_agent").strip()[:100],
        "cfo_contract": _normalized_cfo_contract(candidate.get("cfo_contract"), board),
        "roles": [],
        "shared_whiteboard_keys": _strings(candidate.get("shared_whiteboard_keys", []), limit=32)
        or default_minimal_pipeline_manifest(board)["shared_whiteboard_keys"],
        "steps": [],
        "limits": candidate.get("limits") if isinstance(candidate.get("limits"), dict) else {},
    }
    for index, role in enumerate(candidate.get("roles", []) if isinstance(candidate.get("roles"), list) else []):
        if not isinstance(role, dict):
            continue
        normalized["roles"].append(
            {
                "id": _slug(role.get("id") or role.get("name"), f"role_{index + 1}"),
                "name": str(role.get("name") or role.get("id") or f"Role {index + 1}").strip()[:100],
                "purpose": str(role.get("purpose") or "Contribute to the generated project pipeline.").strip()[:500],
            }
        )
    normalized["roles"] = normalized["roles"][:MAX_ROLES]

    role_ids = {role["id"] for role in normalized["roles"]}
    for index, step in enumerate(candidate.get("steps", []) if isinstance(candidate.get("steps"), list) else []):
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("type", "")).strip()
        clean_step = {
            "id": _slug(step.get("id"), f"step_{index + 1}"),
            "type": step_type,
            "goal": str(step.get("goal", "")).strip()[:1000],
        }
        stages = [stage for stage in _stage_values(step.get("stage")) if stage in ALLOWED_STAGES]
        if stages:
            clean_step["stage"] = stages[0] if len(stages) == 1 else stages
        if step_type == "agent_turn":
            role = _slug(step.get("role"), "")
            clean_step["role"] = role if role in role_ids else (next(iter(role_ids), "builder"))
            clean_step["allowed_actions"] = [
                str(action)
                for action in step.get("allowed_actions", [])
                if str(action) in ALLOWED_ACTION_TYPES
            ][:12]
        for key in ("action", "command", "skill", "name", "args", "patch", "startup_command", "known_limits"):
            if key in step:
                clean_step[key] = step[key]
        normalized["steps"].append(clean_step)
    normalized["steps"] = normalized["steps"][:MAX_STEPS]
    limits = normalized["limits"]
    limits["max_agent_turns_per_step"] = max(1, min(8, int(limits.get("max_agent_turns_per_step", 4) or 4)))
    limits["max_total_steps"] = max(1, min(MAX_STEPS, int(limits.get("max_total_steps", MAX_STEPS) or MAX_STEPS)))
    limits["allow_dynamic_new_steps"] = False

    ok, errors = validate_pipeline_manifest(normalized)
    if ok:
        return normalized
    fallback = default_minimal_pipeline_manifest(board)
    fallback["normalization_fallback_reason"] = "; ".join(errors)[:1000]
    _, missing = validate_required_stages(normalized)
    if missing:
        fallback["missing_required_stages"] = missing
    return fallback


def write_pipeline_manifest(run_dir: str | pathlib.Path, manifest: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(run_dir).resolve() / "pipeline_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
