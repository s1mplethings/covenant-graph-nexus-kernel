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


def _project_goal(whiteboard: dict[str, Any]) -> str:
    for key in ("project_summary", "summary", "goal"):
        text = str(whiteboard.get(key, "")).strip()
        if text:
            return text[:2000]
    facts = _strings(whiteboard.get("known_facts", []), limit=3)
    if facts:
        return "\n".join(facts)[:2000]
    return "Generate the first usable version of the project described in the session."


def default_minimal_pipeline_manifest(whiteboard: dict[str, Any] | None) -> dict[str, Any]:
    board = whiteboard if isinstance(whiteboard, dict) else {}
    goal = _project_goal(board)
    return {
        "kind": MANIFEST_KIND,
        "version": MANIFEST_VERSION,
        "project_goal": goal,
        "source": "planner_agent",
        "roles": [
            {"id": "product", "name": "Product Planner", "purpose": "clarify scope and acceptance"},
            {"id": "builder", "name": "Project Builder", "purpose": "create the project files from the whiteboard"},
            {"id": "qa", "name": "QA Runner", "purpose": "run checks and repair failures"},
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
            "acceptance",
            "acceptance_criteria",
            "delivery_requirements",
        ],
        "steps": [
            {
                "id": "plan",
                "type": "agent_turn",
                "role": "product",
                "goal": "write PROJECT_PLAN.md with first-version scope, assumptions, and acceptance criteria",
                "allowed_actions": ["write_file", "read_file", "use_skill", "search_skills"],
            },
            {
                "id": "build",
                "type": "agent_turn",
                "role": "builder",
                "goal": "create the project files according to PROJECT_PLAN.md and the whiteboard",
                "allowed_actions": ["write_file", "read_file", "list_files", "use_skill", "search_skills"],
            },
            {
                "id": "qa",
                "type": "agent_turn",
                "role": "qa",
                "goal": "inspect the project, run appropriate local checks, and repair failures",
                "allowed_actions": ["read_file", "list_files", "use_skill", "search_skills", "run_command", "write_file"],
            },
            {"id": "package", "type": "package_project", "goal": "create final_project_bundle.zip and delivery_manifest.json"},
        ],
        "limits": {"max_agent_turns_per_step": 3, "max_total_steps": 12, "allow_dynamic_new_steps": False},
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
    return not errors, errors


def normalize_pipeline_manifest(manifest: Any, whiteboard: dict[str, Any] | None) -> dict[str, Any]:
    board = whiteboard if isinstance(whiteboard, dict) else {}
    candidate = manifest if isinstance(manifest, dict) else {}
    normalized = {
        "kind": candidate.get("kind") or MANIFEST_KIND,
        "version": candidate.get("version") or MANIFEST_VERSION,
        "project_goal": str(candidate.get("project_goal") or _project_goal(board)).strip()[:2000],
        "source": str(candidate.get("source") or "planner_agent").strip()[:100],
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
        if step_type == "agent_turn":
            role = _slug(step.get("role"), "")
            clean_step["role"] = role if role in role_ids else (next(iter(role_ids), "builder"))
            clean_step["allowed_actions"] = [
                str(action)
                for action in step.get("allowed_actions", [])
                if str(action) in ALLOWED_ACTION_TYPES
            ][:12]
        for key in ("action", "command", "skill", "name", "args", "patch"):
            if key in step:
                clean_step[key] = step[key]
        normalized["steps"].append(clean_step)
    normalized["steps"] = normalized["steps"][:MAX_STEPS]
    limits = normalized["limits"]
    limits["max_agent_turns_per_step"] = max(1, min(5, int(limits.get("max_agent_turns_per_step", 3) or 3)))
    limits["max_total_steps"] = max(1, min(MAX_STEPS, int(limits.get("max_total_steps", MAX_STEPS) or MAX_STEPS)))
    limits["allow_dynamic_new_steps"] = False

    ok, _ = validate_pipeline_manifest(normalized)
    if ok:
        return normalized
    return default_minimal_pipeline_manifest(board)


def write_pipeline_manifest(run_dir: str | pathlib.Path, manifest: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(run_dir).resolve() / "pipeline_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
