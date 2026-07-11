from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_planner import build_agent_tree_dag
from scripts.agent_tree_shared_context import create_shared_context


def test_agent_tree_build_dag_has_required_stages_and_dependencies() -> None:
    dag = build_agent_tree_dag(create_shared_context("Local AI Knowledge Studio", "goal"))
    stages = {stage["id"]: stage for stage in dag["stages"]}

    for stage_id in ("requirement_freeze", "foundation", "backend_services", "frontend_views", "tests", "visual", "delivery"):
        assert stage_id in stages
        assert stages[stage_id]["agent"]
        assert stages[stage_id].get("expected_files") or stages[stage_id].get("outputs")
        assert stages[stage_id]["verify"]
    assert stages["delivery"]["depends_on"] == ["visual"]
    assert stages["tests"]["depends_on"] == ["frontend_views"]
    assert stages["frontend_views"]["depends_on"] == ["backend_services"]
