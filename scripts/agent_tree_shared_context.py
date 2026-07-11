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


LOCAL_AI_KNOWLEDGE_CONTRACT = [
    "import documents into a local knowledge base",
    "search knowledge base content",
    "summarize source material",
    "track tasks created from knowledge work",
    "generate reports",
    "document local model adapter configuration and limits",
]

LOCAL_STUDIO_OPERATIONS_CONTRACT = [
    "show a dashboard with project overview and production progress",
    "track production tasks with status, owner, priority, and due dates",
    "manage an asset library for local studio files and metadata",
    "track bugs and issues with severity and resolution state",
    "record build and release history",
    "provide docs or production guideline pages",
    "manage a release checklist",
    "manage team members and roles",
    "support search and filtering across operational records",
    "support local import and export workflows",
    "run locally without external SaaS dependencies",
    "include a runnable entry point",
    "include README instructions",
    "include tests for core workflows",
    "include screenshots and final bundle evidence",
]

LOCAL_STUDIO_ALLOWED_CONTEXT_TERMS = [
    "studio operations",
    "dashboard",
    "project overview",
    "production tasks",
    "asset library",
    "bugs",
    "issues",
    "builds",
    "releases",
    "docs",
    "production guidelines",
    "release checklist",
    "team roles",
    "search",
    "filter",
    "import",
    "export",
    "local-first",
]


def build_goal_specific_acceptance_contract(project_name: str, user_goal: str) -> dict[str, Any]:
    goal_text = f"{project_name} {user_goal}".lower()
    if all(term in goal_text for term in ("studio", "operations")) or "local studio operations hub" in goal_text:
        return {
            "kind": "GoalSpecificAcceptanceContract",
            "domain": "local_studio_operations_hub",
            "required_capabilities": list(LOCAL_STUDIO_OPERATIONS_CONTRACT),
            "forbidden_scope": [
                "external SaaS dependency",
                "simple task-board-only output",
                "placeholder-only screenshot",
                "missing runnable entry point",
                "output without tests",
                "output without final bundle",
            ],
        }
    if any(term in goal_text for term in ("knowledge", "知识", "document", "文档", "资料")):
        domain = "local_ai_knowledge_studio"
        capabilities = LOCAL_AI_KNOWLEDGE_CONTRACT
    else:
        domain = "goal_specific_local_application"
        capabilities = [
            "implement the current user goal as the primary product scope",
            "provide local-first runnable application behavior",
            "include domain-specific dashboard or overview",
            "include CRUD or workflow actions required by the goal",
            "include README instructions",
            "include tests for core workflows",
            "include screenshots and final bundle evidence",
        ]
    return {
        "kind": "GoalSpecificAcceptanceContract",
        "domain": domain,
        "required_capabilities": list(capabilities),
        "forbidden_scope": [
            "drift to an unrelated product domain",
            "placeholder-only implementation",
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
    allowed_context_terms = (
        list(LOCAL_STUDIO_ALLOWED_CONTEXT_TERMS)
        if goal_contract["domain"] == "local_studio_operations_hub"
        else list(DEFAULT_ALLOWED_CONTEXT_TERMS)
    )
    return {
        "kind": "AgentTreeSharedContext",
        "project_id": project_id or slugify(project_name),
        "project_name": project_name,
        "user_goal": user_goal,
        "target_project_model": {
            "mode": "local_model",
            "config_needed": True,
            "adapter_required": True,
        },
        "cgkn_backend": {
            "mode": "api",
        },
        "frozen_requirements": [],
        "acceptance_contract": list(goal_contract["required_capabilities"]),
        "goal_specific_acceptance_contract": goal_contract,
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
