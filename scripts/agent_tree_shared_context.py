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


def create_shared_context(
    project_name: str,
    user_goal: str,
    *,
    project_id: str | None = None,
    current_stage: str = "intake",
) -> dict[str, Any]:
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
        "acceptance_contract": [
            "import documents into a local knowledge base",
            "search knowledge base content",
            "summarize source material",
            "track tasks created from knowledge work",
            "generate reports",
            "document local model adapter configuration and limits",
        ],
        "allowed_context_terms": list(DEFAULT_ALLOWED_CONTEXT_TERMS),
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
