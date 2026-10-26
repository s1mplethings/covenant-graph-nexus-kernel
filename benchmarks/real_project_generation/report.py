from __future__ import annotations

import json
import pathlib
from typing import Any


def summarize(root: pathlib.Path) -> dict[str, Any]:
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*/*/generation_receipt.json"))]
    passed = [row for row in receipts if row.get("final_status") == "PASS"]
    return {
        "kind": "CGKNSoftwareProjectGenerationSummary", "schema_version": "1.0",
        "run_count": len(receipts), "pass_count": len(passed),
        "functional_success_rate": len(passed) / len(receipts) if receipts else 0.0,
        "hidden_acceptance_rate": sum(row.get("hidden_acceptance_result") == "PASS" for row in receipts) / len(receipts) if receipts else 0.0,
        "manual_intervention_per_project": sum(int(row.get("manual_intervention", 0)) for row in receipts) / len(receipts) if receipts else 0.0,
        "provider_calls_per_successful_project": sum(int(row.get("provider_call_count", 0)) for row in passed) / len(passed) if passed else 0.0,
        "wall_time_ms_per_successful_project": sum(int(row.get("wall_time_ms", 0)) for row in passed) / len(passed) if passed else 0.0,
        "receipt_hashes": [row.get("receipt_hash") for row in receipts],
    }
