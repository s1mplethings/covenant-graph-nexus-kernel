from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_registry import add_agent, initial_registry


def test_initial_registry_only_has_main_agent() -> None:
    registry = initial_registry()

    assert len(registry["agents"]) == 1
    assert registry["agents"][0]["agent_id"] == "main_agent"
    assert registry["agents"][0]["parent_id"] is None
    assert registry["agents"][0]["depth"] == 0


def test_registry_add_agent_records_parent_child_edge() -> None:
    registry = initial_registry()
    add_agent(registry, {"action_id": "S0001", "parent_agent": "main_agent", "new_agent_id": "backend_branch_agent", "role": "BackendBranchAgent", "depth": 1, "scope": []})

    assert registry["agents"][0]["children"] == ["backend_branch_agent"]
    assert ["main_agent", "backend_branch_agent"] in registry["edges"]
