from __future__ import annotations

from copy import deepcopy
from typing import Any

from .refs import ref_of


def build_contract_pack(flow: dict[str, Any], policy: dict[str, Any], modules: list[dict[str, Any]], artifacts: list[str]) -> dict[str, Any]:
    return {
        "kind": "ContractPack",
        "schema_version": "1",
        "version": "1",
        "task": {
            "kind": "compile",
            "target": f"{flow['id']}@{flow['version']}",
        },
        "allowed_files": policy.get("fs", {}).get("allowed_write", []),
        "denied_files": policy.get("fs", {}).get("denied_write", []),
        "flow": f"{flow['id']}@{flow['version']}",
        "policy": f"{policy['id']}@{policy['version']}",
        "migration": flow.get("metadata", {}).get("migration_target"),
        "required_modules": [f"{m['id']}@{m['version']}" for m in modules],
        "required_artifacts": sorted(artifacts),
        "allowed_graph_edits": policy.get("agent_permissions", {}).get("allowed_edits", []),
        "required_checks": ["schema", "semantic", "compile"],
        "compiler_contract": {
            "no_runtime_execution": True,
            "graph_edits_require_proposal": True,
        },
    }


def build_agent_contract_pack(
    compile_result: dict[str, Any],
    flow: dict[str, Any],
    policy: dict[str, Any],
    modules: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    task_kind: str,
) -> dict[str, Any]:
    module_refs = {node["module_ref"] for node in compile_result.get("compiled_flow", {}).get("nodes", [])}
    artifact_refs = set(compile_result.get("resolved_artifacts", []))
    relevant_modules = sorted((deepcopy(module) for module in modules if ref_of(module) in module_refs), key=ref_of)
    relevant_artifacts = sorted((deepcopy(artifact) for artifact in artifacts if ref_of(artifact) in artifact_refs), key=ref_of)
    policy_ref = ref_of(policy)
    return {
        "kind": "AgentContractPack",
        "schema_version": "1",
        "version": "1",
        "task": {
            "kind": task_kind,
            "target_flow": ref_of(flow),
        },
        "target_flow": ref_of(flow),
        "compiled_flow": deepcopy(compile_result.get("compiled_flow")),
        "symbol_table": _flow_symbol_table_subset(compile_result.get("symbol_table", {})),
        "module_contracts": relevant_modules,
        "artifact_specs": relevant_artifacts,
        "policies": [deepcopy(policy)],
        "diagnostics": deepcopy(compile_result.get("diagnostics", [])),
        "hashes": {
            "surface_hash": compile_result.get("surface_hash"),
            "policy_hash": compile_result.get("policy_hash"),
            "graph_hash": compile_result.get("graph_hash"),
        },
        "surface_hash": compile_result.get("surface_hash"),
        "policy_hash": compile_result.get("policy_hash"),
        "graph_hash": compile_result.get("graph_hash"),
        "allowed_graph_edits": sorted(policy.get("agent_permissions", {}).get("allowed_edits", [])),
        "denied_graph_edits": sorted(policy.get("agent_permissions", {}).get("denied_edits", [])),
        "agent_output_contract": {
            "required_output_kind": "MigrationProof" if task_kind == "migration" else "GraphEditProposal",
            "must_submit_graph_changes_as": "GraphEditProposal",
            "must_return_diagnostics": True,
            "must_not_modify_flow_directly": True,
            "must_not_execute_runtime": True,
        },
        "repair_protocol": {
            "on_schema_error": "fix contract shape and rerun schema validation",
            "on_semantic_error": "use stable CGNK diagnostic code and repair_hints",
            "on_graph_change": "submit proposal, preview, compile, then inspect diagnostics",
        },
        "required_validation_commands": [
            "python scripts/validate_bundle.py",
            "python scripts/validate_bundle.py --schema",
            "python -m unittest discover -v",
            f"python scripts/cgnk_compile.py --flow {ref_of(flow)}",
        ],
        "compiler_contract": {
            "policy_ref": policy_ref,
            "no_runtime_execution": True,
            "no_provider_calls": True,
            "graph_edits_require_proposal": True,
        },
    }


def _flow_symbol_table_subset(symbol_table: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_ref": symbol_table.get("flow_ref"),
        "policy_ref": symbol_table.get("policy_ref"),
        "artifacts": deepcopy(symbol_table.get("artifacts", [])),
        "modules": deepcopy(symbol_table.get("modules", [])),
        "topological_order": deepcopy(symbol_table.get("topological_order", [])),
        "nodes": deepcopy(symbol_table.get("nodes", {})),
        "ports": deepcopy(symbol_table.get("ports", {})),
        "edges": deepcopy(symbol_table.get("edges", [])),
        "gates": deepcopy(symbol_table.get("gates", [])),
    }
