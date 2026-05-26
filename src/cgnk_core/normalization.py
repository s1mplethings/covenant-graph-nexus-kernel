from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from .refs import ref_of


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_edge_id(source: dict[str, Any], target: dict[str, Any]) -> str:
    return "edge." + stable_hash({"source": source, "target": target})[:16]


def endpoint_key(endpoint: dict[str, Any]) -> str:
    if "flow_input" in endpoint:
        return f"flow_input:{endpoint['flow_input']}"
    if "flow_output" in endpoint:
        return f"flow_output:{endpoint['flow_output']}"
    return f"node:{endpoint.get('node')}:{endpoint.get('port')}"


def topological_node_order(flow: dict[str, Any]) -> list[str]:
    nodes = sorted(node["id"] for node in flow.get("nodes", []))
    known = set(nodes)
    incoming: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for edge in flow.get("edges", []):
        source = edge.get("from", {})
        target = edge.get("to", {})
        if "node" in source and "node" in target and source["node"] in known and target["node"] in known:
            outgoing[source["node"]].add(target["node"])
            incoming[target["node"]].add(source["node"])
    ready = sorted(node_id for node_id in nodes if not incoming[node_id])
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for nxt in sorted(outgoing[node_id]):
            incoming[nxt].discard(node_id)
            if not incoming[nxt] and nxt not in ordered and nxt not in ready:
                ready.append(nxt)
        ready.sort()
    if len(ordered) != len(nodes):
        ordered.extend(node_id for node_id in nodes if node_id not in ordered)
    return ordered


def canonical_edges(flow: dict[str, Any]) -> list[dict[str, Any]]:
    edges = []
    for edge in flow.get("edges", []):
        source = deepcopy(edge["from"])
        target = deepcopy(edge["to"])
        edges.append(
            {
                "edge_id": stable_edge_id(source, target),
                "source": source,
                "target": target,
                "source_key": endpoint_key(source),
                "target_key": endpoint_key(target),
            }
        )
    return sorted(edges, key=lambda row: (row["edge_id"], row["source_key"], row["target_key"]))


def build_symbol_table(flow: dict[str, Any], policy: dict[str, Any] | None, modules: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    module_by_ref = {ref_of(module): module for module in modules}
    flow_nodes = {node["id"]: node for node in flow.get("nodes", [])}
    topo_order = topological_node_order(flow)
    canonical_edge_rows = canonical_edges(flow)
    nodes: dict[str, Any] = {}
    ports: dict[str, Any] = {}
    input_bindings: dict[str, dict[str, list[dict[str, Any]]]] = {node_id: {} for node_id in flow_nodes}
    output_bindings: dict[str, dict[str, list[dict[str, Any]]]] = {node_id: {} for node_id in flow_nodes}
    for edge in canonical_edge_rows:
        source = edge["source"]
        target = edge["target"]
        if "node" in target:
            input_bindings.setdefault(target["node"], {}).setdefault(target["port"], []).append(
                {"edge_id": edge["edge_id"], "source": deepcopy(source)}
            )
        if "node" in source:
            output_bindings.setdefault(source["node"], {}).setdefault(source["port"], []).append(
                {"edge_id": edge["edge_id"], "target": deepcopy(target)}
            )
    for node_id in topo_order:
        node = flow_nodes[node_id]
        module = module_by_ref.get(node["uses"], {})
        input_ports = module.get("ports", {}).get("input", {})
        output_ports = module.get("ports", {}).get("output", {})
        nodes[node["id"]] = {
            "node_id": node["id"],
            "module_ref": node["uses"],
            "topological_index": topo_order.index(node["id"]),
            "input_ports": sorted(input_ports),
            "output_ports": sorted(output_ports),
            "input_bindings": {
                port: sorted(input_bindings.get(node["id"], {}).get(port, []), key=lambda row: row["edge_id"])
                for port in sorted(input_ports)
            },
            "output_bindings": {
                port: sorted(output_bindings.get(node["id"], {}).get(port, []), key=lambda row: row["edge_id"])
                for port in sorted(output_ports)
            },
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
        "topological_order": topo_order,
        "nodes": nodes,
        "ports": ports,
        "edges": canonical_edge_rows,
        "gates": sorted(gate["id"] for gate in flow.get("gates", [])),
    }


def build_compiled_flow(flow: dict[str, Any], symbol_table: dict[str, Any]) -> dict[str, Any]:
    node_by_id = {node["id"]: node for node in flow.get("nodes", [])}
    return {
        "flow_ref": ref_of(flow),
        "policy_ref": flow.get("policy_ref"),
        "inputs": deepcopy(flow.get("inputs", {})),
        "outputs": deepcopy(flow.get("outputs", {})),
        "nodes": [
            {
                "node_id": node_id,
                "module_ref": node_by_id[node_id]["uses"],
                "topological_index": symbol_table["nodes"].get(node_id, {}).get("topological_index"),
                "input_ports": symbol_table["nodes"].get(node_id, {}).get("input_ports", []),
                "output_ports": symbol_table["nodes"].get(node_id, {}).get("output_ports", []),
                "input_bindings": symbol_table["nodes"].get(node_id, {}).get("input_bindings", {}),
                "output_bindings": symbol_table["nodes"].get(node_id, {}).get("output_bindings", {}),
            }
            for node_id in symbol_table.get("topological_order", [])
        ],
        "edges": symbol_table["edges"],
        "gates": sorted(deepcopy(flow.get("gates", [])), key=lambda gate: gate["id"]),
    }


def build_normalized_bundle(flow: dict[str, Any], policy: dict[str, Any], modules: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]], diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_table = build_symbol_table(flow, policy, modules, artifacts)
    compiled_flow = build_compiled_flow(flow, symbol_table)
    surface = {
        "inputs": compiled_flow["inputs"],
        "outputs": compiled_flow["outputs"],
        "nodes": [
            {
                "node_id": node["node_id"],
                "module_ref": node["module_ref"],
                "input_ports": node["input_ports"],
                "output_ports": node["output_ports"],
            }
            for node in compiled_flow["nodes"]
        ],
    }
    policy_surface = {
        "policy_ref": ref_of(policy),
        "fs": policy.get("fs", {}),
        "network": policy.get("network", {}),
        "provider": policy.get("provider", {}),
        "risk": policy.get("risk", {}),
        "agent_permissions": policy.get("agent_permissions", {}),
    }
    graph_surface = {
        "flow_ref": ref_of(flow),
        "policy_ref": ref_of(policy),
        "nodes": compiled_flow["nodes"],
        "edges": compiled_flow["edges"],
        "gates": compiled_flow["gates"],
    }
    hashes = {
        "surface_hash": stable_hash(surface),
        "policy_hash": stable_hash(policy_surface),
        "graph_hash": stable_hash(graph_surface),
    }
    return {
        "schema_version": "1",
        "flow_ref": ref_of(flow),
        "policy_ref": ref_of(policy),
        "compiled_flow": compiled_flow,
        "symbol_table": symbol_table,
        "hashes": hashes,
        "surface_hash": hashes["surface_hash"],
        "policy_hash": hashes["policy_hash"],
        "graph_hash": hashes["graph_hash"],
        "artifacts": sorted(artifacts),
        "modules": sorted(ref_of(module) for module in modules),
        "diagnostics": diagnostics,
    }
