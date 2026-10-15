from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_contracts import read_jsonl
from scripts.agent_tree_feedback_router import create_feedback_task


def test_feedback_router_writes_structured_repair_task(tmp_path: pathlib.Path) -> None:
    checkpoint = {
        "stage": "foundation",
        "agent_id": "foundation_leaf",
        "missing_files": ["app/main.py", "requirements.txt"],
        "failed_verification": ["entrypoint_exists"],
    }

    task = create_feedback_task(checkpoint, out_dir=tmp_path)

    assert task["repair_task_id"] == "R0001"
    assert task["target_agent"] == "foundation_leaf"
    assert task["failed_stage"] == "foundation"
    assert task["failed_gate"] == "entrypoint_exists"
    assert "change_project_goal" in task["forbidden_actions"]
    assert read_jsonl(tmp_path / "feedback_tasks.jsonl")[0]["repair_task_id"] == "R0001"
