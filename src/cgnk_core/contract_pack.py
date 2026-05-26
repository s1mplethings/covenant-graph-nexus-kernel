from __future__ import annotations

from typing import Any


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
