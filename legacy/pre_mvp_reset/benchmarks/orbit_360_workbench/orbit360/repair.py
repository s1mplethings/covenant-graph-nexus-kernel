from __future__ import annotations

import pathlib
from typing import Any

from .contracts import REPAIR_REPORT_KIND, SCHEMA_VERSION, OrbitError, add_hash, read_json, write_json
from .planner import downstream_closure
from .runner import load_checkpoint
from .workspace import load_workspace, receipt_for, rewrite_registry


def repair_unit(root: pathlib.Path, target: str, delta: int = 1) -> dict[str, Any]:
    if delta == 0 or not -1000 <= delta <= 1000:
        raise OrbitError("delta must be a non-zero integer between -1000 and 1000")
    root, plan, descriptors = load_workspace(root)
    affected = downstream_closure(plan, {target})
    descriptor = dict(descriptors[target])
    descriptor.pop("unit_sha256", None)
    descriptor["weight"] = max(1, int(descriptor["weight"]) + delta)
    descriptor["revision"] = int(descriptor["revision"]) + 1
    descriptor = add_hash(descriptor, "unit_sha256")
    descriptors[target] = descriptor
    write_json(root / "units" / f"{target}.json", descriptor)
    write_json(root / "receipts" / f"{target}.json", receipt_for(descriptor))
    registry = rewrite_registry(root, plan, descriptors)
    checkpoint = load_checkpoint(root, plan)
    removed = []
    for unit_name in affected:
        if unit_name in checkpoint["results"]:
            checkpoint["results"].pop(unit_name)
            removed.append(unit_name)
    write_json(root / "checkpoint.json", checkpoint)
    report = add_hash(
        {
            "kind": REPAIR_REPORT_KIND,
            "schema_version": SCHEMA_VERSION,
            "workflow_state": "repair_prepared",
            "formal_evidence_status": "NOT_EVALUATED",
            "target": target,
            "delta": delta,
            "target_revision": descriptor["revision"],
            "affected_count": len(affected),
            "affected_units": affected,
            "invalidated_checkpoint_count": len(removed),
            "registry_sha256": registry["registry_sha256"],
        },
        "repair_sha256",
    )
    write_json(root / "repair_report.json", report)
    return report
