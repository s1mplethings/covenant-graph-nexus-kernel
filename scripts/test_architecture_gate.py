from __future__ import annotations

import json
import subprocess
import sys

from kernel_gate_common import P0_CLASSES, ROOT, load_json, result, source_files


def collect_test_metadata() -> dict[str, set[str]]:
    completed = subprocess.run([sys.executable, "scripts/collect_kernel_test_metadata.py"], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    value = json.loads(completed.stdout)
    return {str(item["nodeid"]): set(item.get("markers", [])) for item in value.get("tests", [])}


def check() -> dict:
    errors: list[str] = []
    manifest = load_json("governance/test_coverage_manifest.json")
    mappings = dict(manifest.get("sources", {}))
    actual = source_files()
    try:
        collected = collect_test_metadata()
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return result("CGKNTestArchitectureGate", [f"test_collection_failed:{exc}"], source_count=len(actual), mapped_count=len(mappings))
    for source in sorted(actual - set(mappings)): errors.append(f"unmapped_source:{source}")
    for source in sorted(set(mappings) - actual): errors.append(f"orphan_mapping:{source}")
    for source, entry in mappings.items():
        cases = entry.get("test_cases", [])
        if not cases: errors.append(f"missing_test_cases:{source}")
        covered: set[str] = set()
        for case in cases:
            nodeid = str(case.get("nodeid", ""))
            classes = set(case.get("classes", []))
            markers = collected.get(nodeid)
            if markers is None:
                errors.append(f"orphan_test_mapping:{source}:{nodeid}")
                continue
            undeclared = classes - markers
            if undeclared:
                errors.append(f"test_marker_mismatch:{source}:{nodeid}:{','.join(sorted(undeclared))}")
            covered.update(classes)
        classes = set(entry.get("required_classes", []))
        if entry.get("criticality") == "P0" and not P0_CLASSES.issubset(classes): errors.append(f"p0_classes_incomplete:{source}")
        for required in sorted(classes - covered): errors.append(f"required_class_unbound:{source}:{required}")
        if entry.get("criticality") == "P0" and not {"negative", "boundary"}.issubset(covered): errors.append(f"p0_executed_classes_incomplete:{source}")
        if entry.get("state") and not ({"roundtrip", "recovery", "fault_injection"} & covered): errors.append(f"state_class_missing:{source}")
        if entry.get("security") and "security" not in covered: errors.append(f"security_class_missing:{source}")
        if entry.get("provider") and "fault_injection" not in covered: errors.append(f"provider_fault_class_missing:{source}")
    completeness = load_json("governance/kernel_completeness.json")
    if completeness.get("kernel_foundation") == "COMPLETE":
        try:
            receipt = load_json("governance/kernel_test_receipt.json")
            passed = set(receipt.get("test_node_ids", [])) if receipt.get("final_verdict") == "PASS" else set()
        except (OSError, ValueError, json.JSONDecodeError):
            passed = set()
        for source, entry in mappings.items():
            for case in entry.get("test_cases", []):
                if case.get("nodeid") not in passed: errors.append(f"mapped_test_not_passed:{source}:{case.get('nodeid')}")
    return result("CGKNTestArchitectureGate", errors, source_count=len(actual), mapped_count=len(mappings))


if __name__ == "__main__":
    value = check(); print(json.dumps(value, indent=2)); raise SystemExit(0 if value["status"] == "PASS" else 1)
