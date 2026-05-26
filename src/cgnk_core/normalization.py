from __future__ import annotations

from copy import deepcopy
from typing import Any

from .refs import ref_of


def build_symbol_table(flow: dict[str, Any], policy: dict[str, Any] | None, modules: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    module_by_ref = {ref_of(module): module for module in modules}
    nodes: dict[str, Any] = {}
    ports: dict[str, Any] = {}
    for node in flow.get("nodes", []):
        module = module_by_ref.get(node["uses"], {})
        nodes[node["id"]] = {
            "node_id": node["id"],
            "module_ref": node["uses"],
            "input_ports": sorted(module.get("ports", {}).get("input", {})),
            "output_ports": sorted(module.get("ports", {}).get("output", {})),
        }
        for side in ("input", "output"):
            for port, spec in module.get("ports", {}).get(side, {}).items():
                ports[f"{node['id']}.{side}.{port}"] = {
                    "node_id": node["id"],
                    "module_ref": node["uses"],
                    "direction": side,
                    "port": port,
                    "artifact_ref": spec["artifact_type"],
                    "required": bool(spec.get("required", False)),
                    "multi": bool(spec.get("multi", False)),
                }
    return {
        "flow_ref": ref_of(flow),
        "policy_ref": ref_of(policy) if policy else flow.get("policy_ref"),
        "artifacts": sorted(artifacts),
        "modules": sorted(module_by_ref),
        "nodes": nodes,
        "ports": ports,
        "edges": [
            {
                "edge_id": f"e{i}",
                "source": deepcopy(edge["from"]),
                "target": deepcopy(edge["to"]),
            }
            for i, edge in enumerate(flow.get("edges", []))
        ],
        "gates": [gate["id"] for gate in flow.get("gates", [])],
    }


def build_compiled_flow(flow: dict[str, Any], symbol_table: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_ref": ref_of(flow),
        "policy_ref": flow.get("policy_ref"),
        "inputs": deepcopy(flow.get("inputs", {})),
        "outputs": deepcopy(flow.get("outputs", {})),
        "nodes": [
            {
                "node_id": node["id"],
                "module_ref": node["uses"],
                "input_ports": symbol_table["nodes"].get(node["id"], {}).get("input_ports", []),
                "output_ports": symbol_table["nodes"].get(node["id"], {}).get("output_ports", []),
            }
            for node in flow.get("nodes", [])
        ],
        "edges": symbol_table["edges"],
        "gates": deepcopy(flow.get("gates", [])),
    }


def build_normalized_bundle(flow: dict[str, Any], policy: dict[str, Any], modules: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]], diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_table = build_symbol_table(flow, policy, modules, artifacts)
    compiled_flow = build_compiled_flow(flow, symbol_table)
    return {
        "schema_version": "1",
        "flow_ref": ref_of(flow),
        "policy_ref": ref_of(policy),
        "compiled_flow": compiled_flow,
        "symbol_table": symbol_table,
        "artifacts": sorted(artifacts),
        "modules": sorted(ref_of(module) for module in modules),
        "diagnostics": diagnostics,
    }
