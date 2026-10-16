from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED = {
    "baseline_id", "parent_baseline_id", "source_commit", "source_tree_sha",
    "core_source_hash", "kernel_receipt_hash", "l6_receipt_hash",
    "semantic_experiment_receipt_hash", "profiles", "test_counts", "known_blockers",
    "protected_invariants", "inherits", "added_guarantees", "unchanged_guarantees",
    "removed_guarantees", "created_at",
}


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "baseline_hash"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_baseline(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED - set(value)
    extra = set(value) - REQUIRED - {"kind", "schema_version", "baseline_hash", "evidence_status"}
    if missing:
        errors.append("missing:" + ",".join(sorted(missing)))
    if extra:
        errors.append("extra:" + ",".join(sorted(extra)))
    if not str(value.get("baseline_id", "")).startswith("BASELINE-"):
        errors.append("invalid_baseline_id")
    if value.get("removed_guarantees"):
        errors.append("BREAKING_BASELINE_CHANGE")
    if any(item == "NOT_EVALUATED" for item in value.get("protected_invariants", [])):
        errors.append("unevaluated_guarantee")
    if value.get("baseline_hash") != canonical_hash(value):
        errors.append("baseline_hash_mismatch")
    return errors


def validate_ledger(index: Mapping[str, Any], receipts: Mapping[str, Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    entries = list(index.get("baselines", []))
    ids = [str(item.get("baseline_id", "")) for item in entries]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_baseline_id")
    if index.get("current_baseline_id") not in ids:
        errors.append("current_baseline_missing")
    by_id = {str(item.get("baseline_id")): item for item in entries}
    for baseline_id, receipt in receipts.items():
        errors.extend(f"{baseline_id}:{item}" for item in validate_baseline(receipt))
        entry = by_id.get(baseline_id)
        if entry is None:
            errors.append(f"unindexed_receipt:{baseline_id}")
            continue
        if entry.get("baseline_hash") != receipt.get("baseline_hash"):
            errors.append(f"index_hash_mismatch:{baseline_id}")
        parent = receipt.get("parent_baseline_id")
        if parent is not None and parent not in by_id:
            errors.append(f"unknown_parent:{baseline_id}:{parent}")
    return errors


def load_and_validate(root: pathlib.Path = ROOT) -> dict[str, Any]:
    index = json.loads((root / "governance/baselines/baseline_index.json").read_text(encoding="utf-8"))
    receipts = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in (root / "governance/baselines/receipts").glob("*.json")
    }
    errors = validate_ledger(index, receipts)
    current = json.loads((root / "governance/current_baseline.json").read_text(encoding="utf-8"))
    if current.get("baseline_id") != index.get("current_baseline_id"):
        errors.append("current_pointer_mismatch")
    if receipts.get(str(current.get("baseline_id"))) != current:
        errors.append("current_receipt_mismatch")
    return {"kind": "CGKNBaselineLedgerValidation", "status": "PASS" if not errors else "FAIL", "errors": sorted(errors)}


if __name__ == "__main__":
    value = load_and_validate()
    print(json.dumps(value, indent=2))
    raise SystemExit(0 if value["status"] == "PASS" else 1)
