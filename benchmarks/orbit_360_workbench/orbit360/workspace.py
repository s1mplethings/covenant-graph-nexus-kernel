from __future__ import annotations

import pathlib
from typing import Any

from .contracts import (
    RECEIPT_KIND,
    REGISTRY_KIND,
    SCHEMA_VERSION,
    UNIT_KIND,
    OrbitError,
    add_hash,
    read_json,
    verify_hash,
    write_json,
)
from .planner import validate_plan


def descriptor_for(plan: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    index = int(unit["index"])
    return add_hash(
        {
            "kind": UNIT_KIND,
            "schema_version": SCHEMA_VERSION,
            "id": str(unit["id"]),
            "index": index,
            "layer": int(unit["layer"]),
            "dependencies": list(unit["dependencies"]),
            "weight": ((index * 17 + 11) % 97) + 1,
            "revision": 0,
            "plan_sha256": str(plan["plan_sha256"]),
        },
        "unit_sha256",
    )


def validate_descriptor(descriptor: dict[str, Any], plan: dict[str, Any], expected: dict[str, Any]) -> None:
    if descriptor.get("kind") != UNIT_KIND or descriptor.get("schema_version") != SCHEMA_VERSION:
        raise OrbitError(f"Unsupported work-unit contract: {expected['id']}")
    if not verify_hash(descriptor, "unit_sha256"):
        raise OrbitError(f"Work-unit hash mismatch: {expected['id']}")
    for field in ("id", "index", "layer", "dependencies"):
        if descriptor.get(field) != expected.get(field):
            raise OrbitError(f"Work-unit {field} mismatch: {expected['id']}")
    if descriptor.get("plan_sha256") != plan.get("plan_sha256"):
        raise OrbitError(f"Work-unit plan binding mismatch: {expected['id']}")
    if not isinstance(descriptor.get("weight"), int) or int(descriptor["weight"]) < 1:
        raise OrbitError(f"Work-unit weight is invalid: {expected['id']}")
    if not isinstance(descriptor.get("revision"), int) or int(descriptor["revision"]) < 0:
        raise OrbitError(f"Work-unit revision is invalid: {expected['id']}")


def receipt_for(descriptor: dict[str, Any]) -> dict[str, Any]:
    return add_hash(
        {
            "kind": RECEIPT_KIND,
            "schema_version": SCHEMA_VERSION,
            "unit_id": descriptor["id"],
            "descriptor_sha256": descriptor["unit_sha256"],
            "validation": "valid",
            "formal_evidence_status": "NOT_EVALUATED",
        },
        "receipt_sha256",
    )


def materialize(plan: dict[str, Any], root: pathlib.Path) -> dict[str, Any]:
    validate_plan(plan)
    root = root.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise OrbitError(f"Workspace is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "plan.json", plan)
    registry_entries = []
    for unit in plan["units"]:
        descriptor = descriptor_for(plan, unit)
        unit_path = root / "units" / f"{unit['id']}.json"
        receipt_path = root / "receipts" / f"{unit['id']}.json"
        write_json(unit_path, descriptor)
        write_json(receipt_path, receipt_for(descriptor))
        registry_entries.append(
            {
                "unit_id": unit["id"],
                "path": unit_path.relative_to(root).as_posix(),
                "dependencies": list(unit["dependencies"]),
                "descriptor_sha256": descriptor["unit_sha256"],
            }
        )
    registry = add_hash(
        {
            "kind": REGISTRY_KIND,
            "schema_version": SCHEMA_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "entry_count": len(registry_entries),
            "entries": registry_entries,
        },
        "registry_sha256",
    )
    write_json(root / "interface_registry.json", registry)
    return {
        "ok": True,
        "workspace": str(root),
        "unit_count": plan["unit_count"],
        "receipt_count": len(registry_entries),
        "plan_sha256": plan["plan_sha256"],
        "registry_sha256": registry["registry_sha256"],
        "formal_evidence_status": "NOT_EVALUATED",
    }


def load_workspace(root: pathlib.Path) -> tuple[pathlib.Path, dict[str, Any], dict[str, dict[str, Any]]]:
    root = root.expanduser().resolve()
    plan = read_json(root / "plan.json")
    validate_plan(plan)
    descriptors: dict[str, dict[str, Any]] = {}
    for expected in plan["units"]:
        descriptor = read_json(root / "units" / f"{expected['id']}.json")
        validate_descriptor(descriptor, plan, expected)
        receipt = read_json(root / "receipts" / f"{expected['id']}.json")
        if receipt != receipt_for(descriptor):
            raise OrbitError(f"Boundary receipt is invalid: {expected['id']}")
        descriptors[str(expected["id"])] = descriptor
    registry = read_json(root / "interface_registry.json")
    if registry.get("kind") != REGISTRY_KIND or not verify_hash(registry, "registry_sha256"):
        raise OrbitError("Interface registry is invalid")
    if registry.get("plan_sha256") != plan.get("plan_sha256") or registry.get("entry_count") != plan.get("unit_count"):
        raise OrbitError("Interface registry binding mismatch")
    expected_entries = [
        {
            "unit_id": unit["id"],
            "path": f"units/{unit['id']}.json",
            "dependencies": list(unit["dependencies"]),
            "descriptor_sha256": descriptors[str(unit["id"])]["unit_sha256"],
        }
        for unit in plan["units"]
    ]
    if registry.get("entries") != expected_entries:
        raise OrbitError("Interface registry entries do not match the workspace")
    return root, plan, descriptors


def rewrite_registry(root: pathlib.Path, plan: dict[str, Any], descriptors: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for unit in plan["units"]:
        descriptor = descriptors[str(unit["id"])]
        entries.append(
            {
                "unit_id": unit["id"],
                "path": f"units/{unit['id']}.json",
                "dependencies": list(unit["dependencies"]),
                "descriptor_sha256": descriptor["unit_sha256"],
            }
        )
    registry = add_hash(
        {
            "kind": REGISTRY_KIND,
            "schema_version": SCHEMA_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "entry_count": len(entries),
            "entries": entries,
        },
        "registry_sha256",
    )
    write_json(root / "interface_registry.json", registry)
    return registry
