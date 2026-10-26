from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Mapping, Sequence


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def analyze_oracle(
    direct_rows: Sequence[Mapping[str, Any]],
    architecture_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    direct = {str(row["case_id"]): row for row in direct_rows}
    architecture = {str(row["case_id"]): row for row in architecture_rows}
    if set(direct) != set(architecture):
        raise ValueError("paired runs must contain identical case IDs")
    if not direct:
        raise ValueError("paired runs must not be empty")

    pairs: list[dict[str, Any]] = []
    for case_id in sorted(direct):
        left = direct[case_id]
        right = architecture[case_id]
        direct_pass = bool(left.get("success"))
        architecture_pass = bool(right.get("success"))
        if direct_pass and architecture_pass:
            classification = "BOTH_PASS"
            oracle_route = "DIRECT_CHEAP"
        elif direct_pass:
            classification = "DIRECT_ONLY"
            oracle_route = "DIRECT_CHEAP"
        elif architecture_pass:
            classification = "ARCHITECTURE_ONLY"
            oracle_route = "FULL_CGNK"
        else:
            classification = "BOTH_FAIL"
            oracle_route = "NONE"
        pairs.append({
            "case_id": case_id,
            "domain": str(left.get("domain") or right.get("domain") or "unknown"),
            "difficulty": str(left.get("difficulty") or right.get("difficulty") or "unknown"),
            "direct_success": direct_pass,
            "architecture_success": architecture_pass,
            "classification": classification,
            "oracle_route": oracle_route,
        })

    counts = Counter(pair["classification"] for pair in pairs)
    task_count = len(pairs)
    direct_successes = sum(pair["direct_success"] for pair in pairs)
    architecture_successes = sum(pair["architecture_success"] for pair in pairs)
    oracle_successes = sum(pair["direct_success"] or pair["architecture_success"] for pair in pairs)
    gain_pp = 100.0 * (oracle_successes - direct_successes) / task_count
    opportunity = (
        "CONTINUE_ROUTER_V1"
        if gain_pp >= 5.0 and counts["ARCHITECTURE_ONLY"] > 0
        else "DIRECTIONAL_REVIEW"
        if gain_pp >= 3.0 and counts["ARCHITECTURE_ONLY"] > 0
        else "LOW_STOP_ROUTER_DEVELOPMENT"
    )
    result = {
        "kind": "CGNKArchitectureRoutingOracleAnalysis",
        "schema_version": "1.0",
        "task_count": task_count,
        "direct_successes": direct_successes,
        "architecture_successes": architecture_successes,
        "oracle_successes": oracle_successes,
        "direct_success_rate": direct_successes / task_count,
        "architecture_success_rate": architecture_successes / task_count,
        "oracle_success_rate": oracle_successes / task_count,
        "oracle_gain_percentage_points": gain_pp,
        "classification_counts": dict(sorted(counts.items())),
        "architecture_only_cases": [pair for pair in pairs if pair["classification"] == "ARCHITECTURE_ONLY"],
        "direct_only_cases": [pair for pair in pairs if pair["classification"] == "DIRECT_ONLY"],
        "both_fail_cases": [pair for pair in pairs if pair["classification"] == "BOTH_FAIL"],
        "router_opportunity": opportunity,
        "router_implementation_authorized": opportunity == "CONTINUE_ROUTER_V1",
        "pairs": pairs,
    }
    result["analysis_hash"] = canonical_hash(result)
    return result
