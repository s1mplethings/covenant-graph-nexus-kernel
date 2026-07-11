from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_growth_budget import check_spawn_budget
    from agent_tree_contracts import append_jsonl, now, read_jsonl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_growth_budget import check_spawn_budget
    from scripts.agent_tree_contracts import append_jsonl, now, read_jsonl


def create_spawn_action(
    *,
    out_dir: str | pathlib.Path,
    registry: dict[str, Any],
    budget: dict[str, int],
    parent_agent: str,
    new_agent_id: str,
    role: str,
    depth: int,
    reason: str,
    scope: list[str],
    expected_outputs: list[str],
    verification: list[str],
) -> dict[str, Any]:
    path = pathlib.Path(out_dir) / "spawn_actions.jsonl"
    existing = read_jsonl(path)
    budget_check = check_spawn_budget(registry, budget, parent_agent=parent_agent, new_depth=depth, spawn_action_count=len(existing))
    action = {
        "action_id": f"S{len(existing) + 1:04d}",
        "action": "spawn_agent",
        "parent_agent": parent_agent,
        "new_agent_id": new_agent_id,
        "role": role,
        "depth": depth,
        "reason": reason,
        "scope": list(scope),
        "expected_outputs": list(expected_outputs),
        "verification": list(verification),
        "budget_check": budget_check,
        "created_at": now(),
    }
    append_jsonl(path, action)
    return action


def validate_spawn_action(action: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    required = ("action_id", "action", "parent_agent", "new_agent_id", "role", "reason", "scope", "expected_outputs", "verification")
    for key in required:
        if not action.get(key):
            missing.append(key)
    if action.get("action") != "spawn_agent":
        missing.append("action_spawn_agent")
    return missing
