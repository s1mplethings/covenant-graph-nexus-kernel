from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import read_json, write_json
    from agent_tree_registry import children_of, merge_eligible_children
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import read_json, write_json
    from scripts.agent_tree_registry import children_of, merge_eligible_children


def merge_branch_results(
    *,
    registry: dict[str, Any],
    parent_agent: str,
    out_dir: str | pathlib.Path,
    owned_outputs: list[str] | None = None,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    all_children = children_of(registry, parent_agent)
    children = merge_eligible_children(registry, parent_agent)
    excluded = [
        {"agent_id": str(child["agent_id"]), "reason": "pruned"}
        for child in all_children
        if child.get("status") == "pruned"
    ]
    issues: list[str] = []
    child_results: list[dict[str, Any]] = []
    for child in children:
        agent_id = str(child["agent_id"])
        checkpoint = read_json(out / "checkpoints" / f"{agent_id}.json", {})
        verdict = str(checkpoint.get("verdict", "MISSING"))
        child_results.append({"agent_id": agent_id, "verdict": verdict})
        if verdict != "PASS":
            issues.append(f"{agent_id}:{verdict}")
    result = {
        "parent_agent": parent_agent,
        "children": [str(child["agent_id"]) for child in children],
        "excluded_children": excluded,
        "merge_verdict": "PASS" if children and not issues else "FAIL",
        "required_children_passed": bool(children) and not issues,
        "owned_outputs": list(owned_outputs or []),
        "child_results": child_results,
        "issues": issues,
    }
    write_json(out / "merge_results" / f"{parent_agent}.json", result)
    return result
