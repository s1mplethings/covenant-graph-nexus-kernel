from __future__ import annotations

from typing import Any


def diff_compile_results(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_flow = before.get("compiled_flow") or {}
    after_flow = after.get("compiled_flow") or {}
    before_nodes = {node["node_id"]: node for node in before_flow.get("nodes", [])}
    after_nodes = {node["node_id"]: node for node in after_flow.get("nodes", [])}
    before_edges = {edge["edge_id"]: edge for edge in before_flow.get("edges", [])}
    after_edges = {edge["edge_id"]: edge for edge in after_flow.get("edges", [])}

    module_changed = []
    for node_id in sorted(set(before_nodes) & set(after_nodes)):
        before_module = before_nodes[node_id].get("module_ref")
        after_module = after_nodes[node_id].get("module_ref")
        if before_module != after_module:
            module_changed.append(
                {
                    "node_id": node_id,
                    "before": before_module,
                    "after": after_module,
                }
            )

    before_risk = before.get("effect_summary", {}).get("max_risk", 0)
    after_risk = after.get("effect_summary", {}).get("max_risk", 0)
    diff = {
        "kind": "CompileResultDiff",
        "before_flow_ref": before.get("flow_ref"),
        "after_flow_ref": after.get("flow_ref"),
        "node_added": sorted(set(after_nodes) - set(before_nodes)),
        "node_removed": sorted(set(before_nodes) - set(after_nodes)),
        "edge_added": [after_edges[edge_id] for edge_id in sorted(set(after_edges) - set(before_edges))],
        "edge_removed": [before_edges[edge_id] for edge_id in sorted(set(before_edges) - set(after_edges))],
        "module_changed": module_changed,
        "policy_changed": before.get("policy_ref") != after.get("policy_ref"),
        "risk_increased": after_risk > before_risk,
        "before": {
            "policy_ref": before.get("policy_ref"),
            "max_risk": before_risk,
            "graph_hash": before.get("graph_hash"),
        },
        "after": {
            "policy_ref": after.get("policy_ref"),
            "max_risk": after_risk,
            "graph_hash": after.get("graph_hash"),
        },
    }
    diff["ok"] = not (
        diff["node_added"]
        or diff["node_removed"]
        or diff["edge_added"]
        or diff["edge_removed"]
        or diff["module_changed"]
        or diff["policy_changed"]
        or diff["risk_increased"]
    )
    return diff
