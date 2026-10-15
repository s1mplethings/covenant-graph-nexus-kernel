from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import append_jsonl, read_jsonl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import append_jsonl, read_jsonl


def create_growth_feedback_task(
    *,
    out_dir: str | pathlib.Path,
    target_agent: str,
    failed_agent: str,
    reason: str,
    missing: list[str] | None = None,
    allowed_actions: list[str] | None = None,
    success_condition: str = "checkpoint PASS",
) -> dict[str, Any]:
    path = pathlib.Path(out_dir) / "feedback_tasks.jsonl"
    existing = read_jsonl(path)
    task = {
        "repair_task_id": f"GR{len(existing) + 1:04d}",
        "target_agent": target_agent,
        "failed_agent": failed_agent,
        "reason": reason,
        "missing": list(missing or []),
        "allowed_actions": list(allowed_actions or ["repair_owned_files", "request_parent_merge"]),
        "forbidden_actions": ["change_project_goal", "claim_delivery_pass", "modify_unowned_file"],
        "success_condition": success_condition,
    }
    append_jsonl(path, task)
    return task
