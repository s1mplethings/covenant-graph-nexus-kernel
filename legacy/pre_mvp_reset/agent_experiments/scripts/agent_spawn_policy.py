from __future__ import annotations

from typing import Any

try:
    from agent_growth_budget import check_leaf_size, check_spawn_budget
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_growth_budget import check_leaf_size, check_spawn_budget


def decide_spawn(registry: dict[str, Any], budget: dict[str, int], *, parent_agent: str, new_depth: int) -> dict[str, Any]:
    return check_spawn_budget(registry, budget, parent_agent=parent_agent, new_depth=new_depth)


def decide_leaf_execution(expected_files: list[str], budget: dict[str, int]) -> dict[str, Any]:
    return check_leaf_size(expected_files, budget)
