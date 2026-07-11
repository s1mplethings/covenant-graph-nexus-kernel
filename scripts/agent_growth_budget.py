from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import write_json


DEFAULT_GROWTH_BUDGET = {
    "max_depth": 4,
    "max_agents": 24,
    "max_children_per_agent": 8,
    "max_leaf_expected_files": 4,
    "max_repair_attempts_per_agent": 2,
    "max_spawn_actions": 30,
}


def default_growth_budget() -> dict[str, int]:
    return dict(DEFAULT_GROWTH_BUDGET)


def save_growth_budget(out_dir: str | pathlib.Path, budget: dict[str, int] | None = None) -> pathlib.Path:
    return write_json(pathlib.Path(out_dir) / "growth_budget.json", budget or default_growth_budget())


def check_spawn_budget(
    registry: dict[str, Any],
    budget: dict[str, int],
    *,
    parent_agent: str,
    new_depth: int,
    spawn_action_count: int = 0,
) -> dict[str, Any]:
    agents = registry.get("agents", []) if isinstance(registry.get("agents"), list) else []
    parent = next((agent for agent in agents if agent.get("agent_id") == parent_agent), {})
    children = parent.get("children", []) if isinstance(parent.get("children"), list) else []
    violations: list[str] = []
    if new_depth > int(budget["max_depth"]):
        violations.append("max_depth_exceeded")
    if len(agents) + 1 > int(budget["max_agents"]):
        violations.append("max_agents_exceeded")
    if len(children) + 1 > int(budget["max_children_per_agent"]):
        violations.append("max_children_per_agent_exceeded")
    if spawn_action_count + 1 > int(budget["max_spawn_actions"]):
        violations.append("max_spawn_actions_exceeded")
    return {"allowed": not violations, "violations": violations}


def check_leaf_size(expected_files: list[str], budget: dict[str, int]) -> dict[str, Any]:
    if len(expected_files) > int(budget["max_leaf_expected_files"]):
        return {
            "verdict": "NEEDS_SPLIT",
            "reason": "leaf_expected_files_exceeds_budget",
            "expected_file_count": len(expected_files),
            "max_leaf_expected_files": int(budget["max_leaf_expected_files"]),
        }
    return {"verdict": "OK", "reason": "", "expected_file_count": len(expected_files)}
