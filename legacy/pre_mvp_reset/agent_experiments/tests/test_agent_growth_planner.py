from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_growth_planner import plan_dynamic_growth
from scripts.agent_tree_registry import initial_registry
from scripts.agent_tree_shared_context import create_shared_context


def test_growth_planner_spawns_branches_and_leaves_from_main_agent(tmp_path: pathlib.Path) -> None:
    assert len(initial_registry()["agents"]) == 1
    registry = plan_dynamic_growth(create_shared_context("Local AI Knowledge Studio", "document import search tasks reports local model adapter"), tmp_path)
    agents = {agent["agent_id"]: agent for agent in registry["agents"]}

    assert "backend_branch_agent" in agents
    assert "frontend_branch_agent" in agents
    assert "test_branch_agent" in agents
    backend_leaves = [agent for agent in registry["agents"] if agent.get("parent_id") == "backend_branch_agent"]
    frontend_leaves = [agent for agent in registry["agents"] if agent.get("parent_id") == "frontend_branch_agent"]
    test_leaves = [agent for agent in registry["agents"] if agent.get("parent_id") == "test_branch_agent"]
    assert len(backend_leaves) >= 4
    assert len(frontend_leaves) >= 5
    assert len(test_leaves) >= 2
    assert all(agent["depth"] >= 2 and agent["parent_id"] for agent in backend_leaves + frontend_leaves + test_leaves)
    assert all((tmp_path / "scope_contracts" / f"{agent['agent_id']}.json").exists() for agent in backend_leaves + frontend_leaves + test_leaves)
