from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import write_json


def initial_registry() -> dict[str, Any]:
    return {
        "kind": "DynamicAgentTreeRegistry",
        "root_agent": "main_agent",
        "agents": [
            {
                "agent_id": "main_agent",
                "role": "MainAgent",
                "parent_id": None,
                "children": [],
                "depth": 0,
                "scope": ["project_goal", "planning", "agent_spawning"],
                "status": "active",
                "created_by_action": None,
            }
        ],
        "edges": [],
    }


def agent_by_id(registry: dict[str, Any], agent_id: str) -> dict[str, Any]:
    for agent in registry.get("agents", []):
        if isinstance(agent, dict) and agent.get("agent_id") == agent_id:
            return agent
    return {}


def add_agent(registry: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    parent_id = str(action["parent_agent"])
    new_id = str(action["new_agent_id"])
    if agent_by_id(registry, new_id):
        return registry
    parent = agent_by_id(registry, parent_id)
    children = parent.setdefault("children", [])
    if new_id not in children:
        children.append(new_id)
    agent = {
        "agent_id": new_id,
        "role": action["role"],
        "parent_id": parent_id,
        "children": [],
        "depth": action["depth"],
        "scope": list(action.get("scope", [])),
        "status": "active",
        "created_by_action": action["action_id"],
    }
    if action.get("replaces"):
        agent["replaces"] = str(action["replaces"])
    registry.setdefault("agents", []).append(agent)
    edge = [parent_id, new_id]
    if edge not in registry.setdefault("edges", []):
        registry["edges"].append(edge)
    return registry


def mark_agent_pruned(
    registry: dict[str, Any],
    agent_id: str,
    *,
    pruning_event_id: str,
    replacement: str | None = None,
) -> dict[str, Any]:
    agent = agent_by_id(registry, agent_id)
    if not agent:
        raise KeyError(f"unknown agent: {agent_id}")
    agent["status"] = "pruned"
    agent["pruned_by"] = pruning_event_id
    agent["merge_eligible"] = False
    if replacement:
        agent["replacement"] = replacement
    return agent


def merge_eligible_children(registry: dict[str, Any], parent_id: str) -> list[dict[str, Any]]:
    return [agent for agent in children_of(registry, parent_id) if agent.get("status", "active") != "pruned"]


def save_registry(registry: dict[str, Any], out_dir: str | pathlib.Path, name: str = "agent_tree_registry.json") -> pathlib.Path:
    return write_json(pathlib.Path(out_dir) / name, registry)


def leaf_agents(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        agent
        for agent in registry.get("agents", [])
        if isinstance(agent, dict) and not agent.get("children") and agent.get("agent_id") != registry.get("root_agent")
    ]


def children_of(registry: dict[str, Any], parent_id: str) -> list[dict[str, Any]]:
    ids = agent_by_id(registry, parent_id).get("children", [])
    return [agent_by_id(registry, str(agent_id)) for agent_id in ids if agent_by_id(registry, str(agent_id))]


def render_tree(registry: dict[str, Any], agent_id: str = "main_agent", prefix: str = "") -> str:
    def walk(current: str, line_prefix: str, is_last: bool, is_root: bool) -> list[str]:
        agent = agent_by_id(registry, current)
        if not agent:
            return []
        connector = "" if is_root else ("└── " if is_last else "├── ")
        lines = [f"{line_prefix}{connector}{current}"]
        children = list(agent.get("children", []))
        child_prefix = line_prefix if is_root else line_prefix + ("    " if is_last else "│   ")
        for index, child in enumerate(children):
            lines.extend(walk(str(child), child_prefix, index == len(children) - 1, False))
        return lines

    return "\n".join(walk(agent_id, prefix, True, True))
