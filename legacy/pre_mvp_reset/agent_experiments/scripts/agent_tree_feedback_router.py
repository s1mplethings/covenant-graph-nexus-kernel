from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import DEFAULT_EVAL_DIR, append_jsonl, read_jsonl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, append_jsonl, read_jsonl


ALLOWED_REPAIR_ACTIONS = {
    "foundation": ["create_file", "modify_readme", "add_dependency_file"],
    "backend_services": ["create_service_file", "fix_import", "add_storage_helper"],
    "frontend_views": ["create_template", "create_frontend_entrypoint"],
    "tests": ["create_test", "fix_test_import"],
    "visual": ["create_screenshot_evidence"],
    "delivery": ["rerun_packager", "fix_manifest_reference"],
}


def create_feedback_task(
    checkpoint: dict[str, Any],
    *,
    out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR,
    max_attempts: int = 2,
) -> dict[str, Any]:
    path = pathlib.Path(out_dir) / "feedback_tasks.jsonl"
    existing = read_jsonl(path)
    task = {
        "repair_task_id": f"R{len(existing) + 1:04d}",
        "target_agent": checkpoint.get("agent_id", ""),
        "failed_stage": checkpoint.get("stage", ""),
        "failed_gate": ",".join(checkpoint.get("failed_verification", [])) or "checkpoint",
        "missing": list(checkpoint.get("missing_files", [])),
        "allowed_actions": ALLOWED_REPAIR_ACTIONS.get(str(checkpoint.get("stage", "")), ["repair_stage_output"]),
        "forbidden_actions": ["change_project_goal", "start_new_project", "claim_delivery_pass"],
        "success_condition": f"{checkpoint.get('stage', '')} checkpoint PASS",
        "max_attempts": max_attempts,
    }
    append_jsonl(path, task)
    return task
