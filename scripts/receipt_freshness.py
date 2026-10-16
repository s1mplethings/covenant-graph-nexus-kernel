from __future__ import annotations

import json
import pathlib
from typing import Any

from source_boundaries import ROOT, boundary_identity


RECEIPTS = {
    "kernel": "governance/kernel_test_receipt.json",
    "application": "governance/software_project_generation_receipt.json",
    "experiment": "governance/semantic_artifact_validation_receipt.json",
}


def check_receipt(boundary: str, relative_path: str, *, current_commit: str = "HEAD") -> dict[str, Any]:
    path = ROOT / relative_path
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        source_commit = str(receipt["source_commit"])
        source = boundary_identity(boundary, source_commit)
        current = boundary_identity(boundary, current_commit)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        return {"boundary": boundary, "receipt": relative_path, "status": "FAIL", "reason": str(exc)}
    fresh = source["boundary_hash"] == current["boundary_hash"]
    return {
        "boundary": boundary,
        "receipt": relative_path,
        "status": "PASS" if fresh else "FAIL",
        "receipt_source_commit": source_commit,
        "receipt_boundary_hash": source["boundary_hash"],
        "current_boundary_hash": current["boundary_hash"],
    }


def check_all(*, current_commit: str = "HEAD") -> dict[str, Any]:
    results = [check_receipt(name, path, current_commit=current_commit) for name, path in RECEIPTS.items()]
    return {
        "kind": "CGKNReceiptFreshness",
        "schema_version": "1.0",
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "results": results,
    }


if __name__ == "__main__":
    value = check_all()
    print(json.dumps(value, indent=2))
    raise SystemExit(0 if value["status"] == "PASS" else 1)
