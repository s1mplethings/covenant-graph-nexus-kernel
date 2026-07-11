from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import read_json, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import read_json, write_json


DEFAULT_FORBIDDEN_ACTIONS = [
    "change_project_goal",
    "spawn_unbounded_agents",
    "claim_delivery_pass",
    "modify_unowned_file",
]


def create_scope_contract(
    *,
    agent_id: str,
    role: str,
    parent_id: str | None,
    allowed_files: list[str],
    forbidden_files: list[str] | None = None,
    allowed_actions: list[str] | None = None,
    verification: list[str] | None = None,
) -> dict[str, Any]:
    allowed = {str(path).replace("\\", "/") for path in allowed_files}
    default_forbidden = ["README.md", "app/main.py", "delivery_manifest.json", "final_project_bundle.zip"]
    effective_forbidden = list(forbidden_files) if forbidden_files is not None else [path for path in default_forbidden if path not in allowed]
    return {
        "agent_id": agent_id,
        "role": role,
        "parent_id": parent_id,
        "allowed_files": list(allowed_files),
        "forbidden_files": effective_forbidden,
        "allowed_actions": list(allowed_actions or ["create_file", "modify_owned_file", "request_parent_merge"]),
        "forbidden_actions": list(DEFAULT_FORBIDDEN_ACTIONS),
        "verification": list(verification or ["owned_files_exist"]),
    }


def save_scope_contract(contract: dict[str, Any], out_dir: str | pathlib.Path) -> pathlib.Path:
    return write_json(pathlib.Path(out_dir) / "scope_contracts" / f"{contract['agent_id']}.json", contract)


def load_scope_contract(out_dir: str | pathlib.Path, agent_id: str) -> dict[str, Any]:
    return read_json(pathlib.Path(out_dir) / "scope_contracts" / f"{agent_id}.json", {})


def validate_scope_contract(contract: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not contract.get("agent_id"):
        issues.append("missing_agent_id")
    if not contract.get("role"):
        issues.append("missing_role")
    if "Leaf" in str(contract.get("role", "")) and not contract.get("allowed_files"):
        issues.append("leaf_missing_allowed_files")
    forbidden_actions = set(contract.get("forbidden_actions", []))
    if "claim_delivery_pass" not in forbidden_actions:
        issues.append("missing_claim_delivery_pass_forbid")
    if "modify_unowned_file" not in forbidden_actions:
        issues.append("missing_modify_unowned_file_forbid")
    return issues


def check_scope_write(contract: dict[str, Any], attempted_files: list[str]) -> dict[str, Any]:
    allowed = {str(path).replace("\\", "/") for path in contract.get("allowed_files", [])}
    forbidden = {str(path).replace("\\", "/") for path in contract.get("forbidden_files", [])}
    violations: list[str] = []
    for raw in attempted_files:
        item = str(raw).replace("\\", "/")
        if item in forbidden or item not in allowed:
            violations.append(item)
    return {"ok": not violations, "violations": violations}
