from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_checkpoint import run_checkpoint
from scripts.agent_tree_feedback_router import create_feedback_task
from scripts.agent_tree_planner import build_agent_tree_dag, can_execute_stage
from scripts.agent_tree_shared_context import create_shared_context


def test_checkpoint_blocks_downstream_when_foundation_is_missing_entrypoint(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# App\n\nRun with `python app/main.py`.\n", encoding="utf-8")
    (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    context = create_shared_context("Local AI Knowledge Studio", "goal")
    dag = build_agent_tree_dag(context)

    checkpoint = run_checkpoint(
        stage="foundation",
        agent_id="foundation_leaf",
        project_dir=project,
        out_dir=tmp_path,
        expected_files=["README.md", "requirements.txt", "app/main.py"],
        verification=["entrypoint_exists", "dependency_file_exists", "startup_command_present"],
    )
    task = create_feedback_task(checkpoint, out_dir=tmp_path)

    assert checkpoint["verdict"] == "FAIL"
    assert checkpoint["can_continue"] is False
    assert can_execute_stage(dag, {"foundation": checkpoint}, "backend_services") is False
    assert task["target_agent"] == "foundation_leaf"
    assert "app/main.py" in task["missing"]
