from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_growth_budget import default_growth_budget
from scripts.agent_spawn_policy import decide_leaf_execution, decide_spawn
from scripts.agent_tree_registry import initial_registry


def test_spawn_policy_uses_budget_boundaries() -> None:
    budget = default_growth_budget()
    registry = initial_registry()

    assert decide_spawn(registry, budget, parent_agent="main_agent", new_depth=1)["allowed"] is True
    assert decide_spawn(registry, budget, parent_agent="main_agent", new_depth=99)["allowed"] is False
    assert decide_leaf_execution(["a.py"], budget)["verdict"] == "OK"
    assert decide_leaf_execution(["a.py", "b.py", "c.py", "d.py", "e.py"], budget)["verdict"] == "NEEDS_SPLIT"
