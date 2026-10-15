from __future__ import annotations

import json

from kernel_gate_common import VALID_COMPLETENESS, load_json, module_file, result
from test_architecture_gate import check as coverage_check


def check() -> dict:
    errors: list[str] = []
    value = load_json("governance/kernel_completeness.json")
    if value.get("functional_readiness") != "LEVEL_4": errors.append("functional_readiness_changed")
    if value.get("kernel_foundation") not in {"PARTIAL", "COMPLETE", "BLOCKED"}: errors.append("invalid_kernel_foundation")
    layers = dict(value.get("layers", {}))
    lower_incomplete = False
    for level in sorted(layers):
        entry = layers[level]
        status = entry.get("status")
        if status not in VALID_COMPLETENESS: errors.append(f"invalid_status:{level}")
        if status == "COMPLETE":
            if entry.get("blockers"): errors.append(f"complete_with_blocker:{level}")
            if not entry.get("evidence"): errors.append(f"complete_without_evidence:{level}")
            if lower_incomplete: errors.append(f"upper_complete_with_lower_incomplete:{level}")
        elif level != "L6":
            lower_incomplete = True
    if value.get("kernel_foundation") == "COMPLETE" and any(entry.get("status") != "COMPLETE" for level, entry in layers.items() if level != "L6"):
        errors.append("foundation_complete_with_incomplete_layer")
    coverage = coverage_check()
    if coverage["status"] != "PASS": errors.append("test_coverage_manifest_failed")
    return result("CGKNKernelCompletenessGate", errors, kernel_foundation=value.get("kernel_foundation"))


if __name__ == "__main__":
    value = check(); print(json.dumps(value, indent=2)); raise SystemExit(0 if value["status"] == "PASS" else 1)
