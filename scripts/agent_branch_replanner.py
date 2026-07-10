from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import append_jsonl, now, read_jsonl
    from agent_tree_registry import add_agent, agent_by_id, mark_agent_pruned
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import append_jsonl, now, read_jsonl
    from scripts.agent_tree_registry import add_agent, agent_by_id, mark_agent_pruned


def replan_branch(
    *,
    out_dir: str | pathlib.Path,
    registry: dict[str, Any],
    signal: dict[str, Any],
    action: str,
    new_leaf_id: str | None = None,
    new_children: list[str] | None = None,
    scope: list[str] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    path = pathlib.Path(out_dir) / "branch_replans.jsonl"
    failed_leaf = str(signal["from_leaf"])
    parent = str(signal["to_parent"])
    event_id = str(signal["pruning_event_id"])
    failed = agent_by_id(registry, failed_leaf)
    if not failed:
        raise KeyError(f"unknown failed leaf: {failed_leaf}")

    replan: dict[str, Any] = {
        "replan_id": f"BR{len(read_jsonl(path)) + 1:04d}",
        "parent_agent": parent,
        "failed_leaf": failed_leaf,
        "action": action,
        "reason": reason or signal.get("failure_type", "leaf failure"),
        "inherits_context_from": failed_leaf,
        "context_reduced": True,
        "created_at": now(),
    }
    replacements: list[str] = []
    if action in {"spawn_replacement_leaf", "switch_leaf_provider_mode", "reduce_leaf_scope"}:
        replacement = new_leaf_id or f"{failed_leaf}_v2"
        replacements = [replacement]
        replan["new_leaf_id"] = replacement
        replan["scope"] = list(scope or failed.get("scope", []))
    elif action == "split_leaf_into_smaller_leaves":
        replacements = list(new_children or [f"{failed_leaf}_part_1", f"{failed_leaf}_part_2"])
        replan["new_children"] = replacements
    elif action == "stop_branch":
        agent_by_id(registry, parent)["status"] = "blocked"
        replan["branch_status"] = "blocked"
    else:
        raise ValueError(f"unsupported replan action: {action}")

    mark_agent_pruned(
        registry,
        failed_leaf,
        pruning_event_id=event_id,
        replacement=replacements[0] if len(replacements) == 1 else None,
    )
    for index, replacement in enumerate(replacements, start=1):
        source_scope = list(scope or failed.get("scope", []))
        if action == "split_leaf_into_smaller_leaves":
            replacement_scope = source_scope[index - 1 :: len(replacements)]
        else:
            replacement_scope = source_scope
        add_agent(
            registry,
            {
                "action_id": f"{replan['replan_id']}-S{index}",
                "parent_agent": parent,
                "new_agent_id": replacement,
                "role": failed.get("role", "ReplacementLeafAgent"),
                "depth": failed.get("depth", 2),
                "scope": replacement_scope,
                "replaces": failed_leaf,
            },
        )
    append_jsonl(path, replan)
    return replan


apply_branch_replan = replan_branch
