from __future__ import annotations

import json
from typing import Any


INITIAL_PROJECT_VERSION = "0.1.0"


def apply_minimum_version_governance(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the universal VERSION truth without creating a parallel project authority."""
    result = [dict(item) for item in files]
    paths = {str(item.get("path", "")).replace("\\", "/") for item in result}
    if "VERSION" not in paths:
        result.append({"path": "VERSION", "content": INITIAL_PROJECT_VERSION + "\n"})
    return result


def version_governance_prompt() -> str:
    return (
        "Version governance is part of the project contract. Every new project must contain one VERSION file. "
        "For a medium or large long-lived project, also create governance/current_architecture.json and create "
        "governance/deprecation_registry.json only when real read/import compatibility remains. A structural upgrade "
        "must name supersedes, migrate consumers, remove the old producer and entrypoint, and retain an old reader "
        "only as COMPAT_ONLY with remove_in. Never create old/new/v2/final_v2 parallel production paths."
    )


def validate_upgrade(*, active_implementations: list[dict[str, Any]], compatibility_items: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    owners: dict[str, list[str]] = {}
    superseded_ids: set[str] = set()
    for item in active_implementations:
        responsibility = str(item.get("responsibility", ""))
        item_id = str(item.get("id", ""))
        if item.get("state") == "ACTIVE":
            owners.setdefault(responsibility, []).append(item_id)
            declared = item.get("supersedes")
            if not isinstance(declared, list):
                failures.append(f"supersedes_missing:{item_id}")
            else:
                superseded_ids.update(str(value) for value in declared)
    for responsibility, ids in owners.items():
        if responsibility and len(ids) > 1:
            failures.append(f"duplicate_active_authority:{responsibility}")
    for item in compatibility_items:
        item_id = str(item.get("id", ""))
        if item.get("state") != "COMPAT_ONLY":
            failures.append(f"compatibility_state_invalid:{item_id}")
        if not item.get("remove_in"):
            failures.append(f"compatibility_remove_in_missing:{item_id}")
        operations = {str(value).lower() for value in item.get("allowed_operations", [])}
        if operations & {"write", "produce", "create"}:
            failures.append(f"compatibility_writer_forbidden:{item_id}")
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "active_owners": owners,
        "superseded": sorted(superseded_ids),
        "compatibility_items": [str(item.get("id", "")) for item in compatibility_items],
        "failures": failures,
    }


def render_current_architecture(*, product_version: str, authorities: dict[str, str | None], supersedes: list[str]) -> str:
    document = {
        "kind": "ProjectCurrentArchitecture",
        "schema_version": "1.0",
        "product_version": product_version,
        "supersedes": list(supersedes),
        "authorities": dict(authorities),
        "forbidden_parallel_authorities": True,
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
