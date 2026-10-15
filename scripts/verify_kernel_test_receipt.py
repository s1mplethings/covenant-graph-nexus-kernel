from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

from kernel_source_identity import ROOT, identity


def _canonical_hash(value: dict) -> str:
    payload = {key: item for key, item in value.items() if key != "receipt_hash"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def verify(path: pathlib.Path) -> dict:
    errors: list[str] = []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        source = identity(str(value["source_commit"]))
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        return {"kind": "CGKNKernelTestReceiptVerification", "status": "FAIL", "errors": [f"receipt_unreadable:{exc}"]}
    for field in ("source_commit", "source_tree_sha", "core_source_hash"):
        if value.get(field) != source.get(field): errors.append(f"source_identity_mismatch:{field}")
    if value.get("receipt_hash") != _canonical_hash(value): errors.append("receipt_hash_mismatch")
    totals = value.get("totals", {})
    if totals.get("failed") or totals.get("errors") or value.get("final_verdict") != "PASS": errors.append("receipt_not_pass")
    coverage_path = ROOT / "governance/kernel_coverage_report.json"
    if not coverage_path.is_file() or value.get("coverage_file_hash") != "sha256:" + hashlib.sha256(coverage_path.read_bytes()).hexdigest(): errors.append("coverage_hash_mismatch")
    return {"kind": "CGKNKernelTestReceiptVerification", "status": "PASS" if not errors else "FAIL", "errors": sorted(errors), "source_commit": value.get("source_commit")}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--receipt", default="governance/kernel_test_receipt.json"); args = parser.parse_args()
    result = verify(ROOT / args.receipt); print(json.dumps(result, indent=2)); return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
