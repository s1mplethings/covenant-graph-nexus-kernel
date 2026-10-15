from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_growth_budget import check_leaf_size, check_spawn_budget, default_growth_budget
from scripts.agent_tree_registry import initial_registry


def test_growth_budget_rejects_depth_agent_count_children_and_leaf_size() -> None:
    budget = default_growth_budget()
    registry = initial_registry()

    assert check_spawn_budget(registry, budget, parent_agent="main_agent", new_depth=budget["max_depth"] + 1)["allowed"] is False

    full_registry = initial_registry()
    for index in range(budget["max_agents"] - 1):
        full_registry["agents"].append({"agent_id": f"a{index}", "children": [], "depth": 1})
    assert check_spawn_budget(full_registry, budget, parent_agent="main_agent", new_depth=1)["allowed"] is False

    child_registry = initial_registry()
    child_registry["agents"][0]["children"] = [f"c{index}" for index in range(budget["max_children_per_agent"])]
    assert check_spawn_budget(child_registry, budget, parent_agent="main_agent", new_depth=1)["allowed"] is False

    oversized = [f"file_{index}.py" for index in range(budget["max_leaf_expected_files"] + 1)]
    assert check_leaf_size(oversized, budget)["verdict"] == "NEEDS_SPLIT"
