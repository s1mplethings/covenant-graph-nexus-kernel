from __future__ import annotations

import math
from typing import Any

from .contracts import PLAN_KIND, SCHEMA_VERSION, OrbitError, add_hash, verify_hash


DEFAULT_UNIT_COUNT = 360
DEFAULT_WIDTH = 35
MAX_UNIT_COUNT = 5000
MAX_WIDTH = 256


def unit_id(index: int) -> str:
    return f"unit_{index:03d}"


def build_plan(unit_count: int = DEFAULT_UNIT_COUNT, width: int = DEFAULT_WIDTH) -> dict[str, Any]:
    if not 1 <= unit_count <= MAX_UNIT_COUNT:
        raise OrbitError(f"unit_count must be between 1 and {MAX_UNIT_COUNT}")
    if not 1 <= width <= min(MAX_WIDTH, unit_count):
        raise OrbitError(f"width must be between 1 and {min(MAX_WIDTH, unit_count)}")
    units = []
    for index in range(unit_count):
        units.append(
            {
                "id": unit_id(index),
                "index": index,
                "layer": index // width,
                "dependencies": [unit_id(index - width)] if index >= width else [],
            }
        )
    return add_hash(
        {
            "kind": PLAN_KIND,
            "schema_version": SCHEMA_VERSION,
            "unit_count": unit_count,
            "width": width,
            "layer_count": math.ceil(unit_count / width),
            "units": units,
        },
        "plan_sha256",
    )


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("kind") != PLAN_KIND or plan.get("schema_version") != SCHEMA_VERSION:
        raise OrbitError("Unsupported ORBIT-360 plan contract")
    if not verify_hash(plan, "plan_sha256"):
        raise OrbitError("Plan hash mismatch")
    unit_count = plan.get("unit_count")
    width = plan.get("width")
    if not isinstance(unit_count, int) or not isinstance(width, int):
        raise OrbitError("Plan unit_count and width must be integers")
    expected = build_plan(unit_count, width)
    if plan != expected:
        raise OrbitError("Plan structure does not match the deterministic dependency contract")


def downstream_closure(plan: dict[str, Any], targets: set[str]) -> list[str]:
    validate_plan(plan)
    known = {str(item["id"]) for item in plan["units"]}
    unknown = sorted(targets - known)
    if unknown:
        raise OrbitError("Unknown repair target(s): " + ", ".join(unknown))
    dependents: dict[str, list[str]] = {name: [] for name in known}
    for item in plan["units"]:
        for dependency in item["dependencies"]:
            dependents[str(dependency)].append(str(item["id"]))
    affected = set(targets)
    queue = list(sorted(targets))
    while queue:
        current = queue.pop(0)
        for dependent in dependents[current]:
            if dependent not in affected:
                affected.add(dependent)
                queue.append(dependent)
    order = {str(item["id"]): int(item["index"]) for item in plan["units"]}
    return sorted(affected, key=order.__getitem__)
