from __future__ import annotations

import json

from kernel_gate_common import P0_CLASSES, ROOT, load_json, result, source_files


def check() -> dict:
    errors: list[str] = []
    manifest = load_json("governance/test_coverage_manifest.json")
    mappings = dict(manifest.get("sources", {}))
    actual = source_files()
    for source in sorted(actual - set(mappings)): errors.append(f"unmapped_source:{source}")
    for source in sorted(set(mappings) - actual): errors.append(f"orphan_mapping:{source}")
    for source, entry in mappings.items():
        tests = entry.get("tests", [])
        if not tests: errors.append(f"missing_tests:{source}")
        for test in tests:
            if not (ROOT / str(test)).is_file(): errors.append(f"missing_test_file:{source}:{test}")
        classes = set(entry.get("required_classes", []))
        if entry.get("criticality") == "P0" and not P0_CLASSES.issubset(classes): errors.append(f"p0_classes_incomplete:{source}")
    return result("CGKNTestArchitectureGate", errors, source_count=len(actual), mapped_count=len(mappings))


if __name__ == "__main__":
    value = check(); print(json.dumps(value, indent=2)); raise SystemExit(0 if value["status"] == "PASS" else 1)
