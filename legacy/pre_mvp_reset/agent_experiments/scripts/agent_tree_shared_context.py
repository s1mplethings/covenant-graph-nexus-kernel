from __future__ import annotations

import argparse
import pathlib
from typing import Any

try:
    from agent_tree_contracts import (
        DEFAULT_ALLOWED_CONTEXT_TERMS,
        DEFAULT_EVAL_DIR,
        DEFAULT_FORBIDDEN_CONTEXT_TERMS,
        now,
        slugify,
        write_json,
    )
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import (
        DEFAULT_ALLOWED_CONTEXT_TERMS,
        DEFAULT_EVAL_DIR,
        DEFAULT_FORBIDDEN_CONTEXT_TERMS,
        now,
        slugify,
        write_json,
    )

try:
    import requirement_decision_lane
except ModuleNotFoundError:  # pragma: no cover
    from scripts import requirement_decision_lane


def build_goal_specific_acceptance_contract(project_name: str, user_goal: str) -> dict[str, Any]:
    goal_spec = requirement_decision_lane.build_goal_spec(user_goal or project_name)
    project_plan = requirement_decision_lane.build_goal_project_plan(goal_spec)
    return {
        "kind": "GoalSpecificAcceptanceContract",
        "status": goal_spec.get("status", "NEEDS_REWORK"),
        "domain": goal_spec.get("domain", "generic_custom"),
        "required_capabilities": [
            str(item).replace("_", " ") for item in goal_spec.get("capabilities", [])
        ],
        "acceptance_behaviors": list(goal_spec.get("acceptance_behaviors", [])),
        "goal_spec": goal_spec,
        "project_plan": project_plan,
        "forbidden_scope": [
            "drift to an unrelated product domain",
            "placeholder-only implementation",
            "silent fallback to an unrelated product template",
            "missing runnable entry point",
            "output without tests",
            "output without final bundle",
        ],
    }


def create_shared_context(
    project_name: str,
    user_goal: str,
    *,
    project_id: str | None = None,
    current_stage: str = "intake",
) -> dict[str, Any]:
    goal_contract = build_goal_specific_acceptance_contract(project_name, user_goal)
    goal_spec = goal_contract["goal_spec"]
    project_plan = goal_contract["project_plan"]
    allowed_context_terms = list(
        dict.fromkeys(
            [str(item).replace("_", " ") for item in goal_spec.get("capabilities", [])]
            + [str(item).replace("_", " ") for item in goal_spec.get("interfaces", [])]
            + [str(item) for item in goal_spec.get("entities", [])]
        )
    ) or list(DEFAULT_ALLOWED_CONTEXT_TERMS)
    model_adapter_required = "configure_local_model_adapter" in goal_spec.get("capabilities", [])
    return {
        "kind": "AgentTreeSharedContext",
        "project_id": project_id or slugify(project_name),
        "project_name": project_name,
        "user_goal": user_goal,
        "target_project_model": {
            "mode": "local_model" if model_adapter_required else "local_application",
            "config_needed": model_adapter_required,
            "adapter_required": model_adapter_required,
        },
        "cgkn_backend": {
            "mode": "api",
        },
        "frozen_requirements": [],
        "acceptance_contract": list(goal_contract["required_capabilities"]),
        "goal_specific_acceptance_contract": goal_contract,
        "goal_spec": goal_spec,
        "project_plan": project_plan,
        "allowed_context_terms": allowed_context_terms,
        "forbidden_context_terms": list(DEFAULT_FORBIDDEN_CONTEXT_TERMS),
        "current_stage": current_stage,
        "created_at": now(),
    }


def save_shared_context(context: dict[str, Any], out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR) -> pathlib.Path:
    return write_json(pathlib.Path(out_dir) / "shared_context.json", context)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--out", default=str(DEFAULT_EVAL_DIR))
    args = parser.parse_args()
    save_shared_context(create_shared_context(args.project_name, args.goal), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
