from __future__ import annotations

import copy
import hashlib
import json
import math
import pathlib
import statistics
import subprocess
from collections import defaultdict
from typing import Any, Iterable, Mapping

from cgkn.application.capability_routing.benchmarks import decision_cases, real_product_registry
from cgkn.application.capability_routing.contracts import DecisionLevel, stable_hash
from cgkn.application.capability_routing.decision import DecisionRouter
from cgkn.application.capability_routing.formal import (
    FORMAL_BENCHMARK_VERSION,
    _call_cost,
    _evaluate_strategy,
    _model_call,
    _task_for,
    _topk_context,
)
from cgkn.application.capability_routing.decision import policy_hashes
from cgkn.application.capability_routing.search import CapabilitySearchIndex
from cgkn.providers import CGKNModelRouting, CompletionClient, ModelRoleConfig


PB027_VERSION = "strong-escalation-evidence-v1"
_FROZEN_RELEVANT_PATHS = (
    "cgkn/application/capability_routing",
    "cgkn/providers",
    "config/provider_profiles/gateway_model_routing.json",
)
_TOKEN_FIELDS = (
    "input_tokens",
    "cached_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def _sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _decision_document(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = value.get("decision") if isinstance(value.get("decision"), Mapping) else value
    result = dict(candidate)
    if result.get("kind") != "CapabilityDecisionFormalReceipt":
        raise ValueError("PB-027 requires a CapabilityDecisionFormalReceipt")
    if result.get("benchmark_version") != FORMAL_BENCHMARK_VERSION:
        raise ValueError("PB-027 formal benchmark version mismatch")
    if len(result.get("calls") or ()) != 28:
        raise ValueError("PB-027 requires the frozen 28-call paired receipt")
    return result


def load_document(path: pathlib.Path | str) -> dict[str, Any]:
    value = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("evidence document root must be an object")
    return value


def _current_suite_identity(routing: CGKNModelRouting) -> dict[str, Any]:
    return {
        "route_config_hash": routing.config_hash,
        "policy_hashes": policy_hashes(),
    }


def _require_semantic_compatibility(
    decision: Mapping[str, Any],
    routing: CGKNModelRouting,
    *,
    product_source_commit: str,
    product_source_tree: str,
    repository_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    current = _current_suite_identity(routing)
    exact_source = (
        decision.get("source_commit") == product_source_commit
        and decision.get("source_tree") == product_source_tree
    )
    checks = {
        "source_identity_exact": exact_source,
        "previous_suite_hash_preserved": bool(decision.get("suite_hash")),
        "route_config_hash_equal": current["route_config_hash"] == decision.get("route_config_hash"),
        "policy_hashes_equal": current["policy_hashes"] == decision.get("policy_hashes"),
        "case_manifest_complete": len(decision.get("case_manifest") or ()) == len(decision_cases()),
    }
    relevant_diff: list[str] = []
    if repository_root and decision.get("source_commit") != product_source_commit:
        completed = subprocess.run(
            [
                "git", "diff", "--name-only", str(decision.get("source_commit")),
                product_source_commit, "--", *_FROZEN_RELEVANT_PATHS,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        relevant_diff = [line for line in completed.stdout.splitlines() if line.strip()]
        checks["relevant_source_paths_byte_identical"] = not relevant_diff
    else:
        checks["relevant_source_paths_byte_identical"] = True
    required = (
        checks["route_config_hash_equal"]
        and checks["policy_hashes_equal"]
        and checks["case_manifest_complete"]
        and (exact_source or checks["relevant_source_paths_byte_identical"])
    )
    if not required:
        raise ValueError("previous evidence is not semantically compatible with the frozen product source")
    return {
        "previous_source_commit": decision.get("source_commit"),
        "previous_source_tree": decision.get("source_tree"),
        "product_source_commit": product_source_commit,
        "product_source_tree": product_source_tree,
        "checks": checks,
        "relevant_paths": list(_FROZEN_RELEVANT_PATHS),
        "relevant_diff": relevant_diff,
        "previous_suite_hash": decision.get("suite_hash"),
        "suite_hash_reconstruction_note": "NOT_RECOMPUTED_REGISTRY_HASHES_INCLUDE_REBUILD_IDENTITY",
        **current,
    }


def run_single_replacement(
    *,
    client: CompletionClient,
    routing: CGKNModelRouting,
    previous_receipt: Mapping[str, Any],
    product_source_commit: str,
    product_source_tree: str,
    harness_commit: str,
    run_id: str,
    case_id: str = "strong-6",
    role: str = "strong",
    repository_root: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Repeat one frozen transport failure without changing benchmark semantics."""
    decision = _decision_document(previous_receipt)
    original = next(
        (
            dict(row)
            for row in decision["calls"]
            if row.get("case_id") == case_id and row.get("role") == role
        ),
        None,
    )
    if original is None or original.get("status") != "CALL_FAILED":
        raise ValueError("replacement is allowed only for one frozen provider call failure")
    if original.get("error_class") not in {"outcome_unknown", "gateway_unavailable", "timeout"}:
        raise ValueError("replacement is forbidden for semantic or validator failure")
    compatibility = _require_semantic_compatibility(
        decision,
        routing,
        product_source_commit=product_source_commit,
        product_source_tree=product_source_tree,
        repository_root=pathlib.Path(repository_root) if repository_root else None,
    )
    if role != "strong":
        raise ValueError("PB-027 replacement is scoped to the missing strong route")

    cases = {case.case_id: case for case in decision_cases()}
    case = cases.get(case_id)
    if case is None:
        raise ValueError("replacement case is not in the frozen decision suite")
    task = _task_for(case)
    context = _topk_context(CapabilitySearchIndex.rebuild(real_product_registry()), task)
    replacement = _model_call(
        client,
        case=case,
        task=task,
        role_name=role,
        config=routing.agent,
        run_id=run_id,
        registry_context=context,
    )
    if replacement.get("prompt_hash") != original.get("prompt_hash"):
        raise RuntimeError("replacement prompt hash differs from the original frozen call")
    if replacement.get("schema_hash") != original.get("schema_hash"):
        raise RuntimeError("replacement schema hash differs from the original frozen call")
    body = {
        "kind": "PB027ProviderFailureReplacement",
        "schema_version": "1.0",
        "benchmark_version": decision["benchmark_version"],
        "product_source_commit": product_source_commit,
        "product_source_tree": product_source_tree,
        "harness_commit": harness_commit,
        "run_id": run_id,
        "replacement_policy": "ONE_PREDEFINED_REPLACEMENT_FOR_PROVIDER_INFRASTRUCTURE_FAILURE",
        "source_compatibility": compatibility,
        "semantic_use": "REPLACE_ORIGINAL_CALL_ONLY_IF_COMPLETE_USAGE_IS_REPORTED",
        "operational_use": "COUNT_ORIGINAL_AND_REPLACEMENT",
        "original_call": original,
        "replacement_call": replacement,
        "contains_credentials": False,
        "raw_provider_text_stored": False,
    }
    return body | {"receipt_hash": stable_hash(body)}


def _usage_state(call: Mapping[str, Any]) -> str:
    values = [call.get(name) for name in ("input_tokens", "output_tokens", "total_tokens")]
    if all(isinstance(value, int) for value in values):
        return "KNOWN"
    if any(isinstance(value, int) for value in values):
        return "PARTIAL"
    return "UNKNOWN"


def _known_sum(rows: Iterable[Mapping[str, Any]], field: str) -> int:
    return sum(int(row[field]) for row in rows if isinstance(row.get(field), int))


def _exact_sum(rows: list[Mapping[str, Any]], field: str) -> int | None:
    return _known_sum(rows, field) if all(isinstance(row.get(field), int) for row in rows) else None


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 3)


def _call_cost_components(call: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(catalog.get("records", {}).get(str(call.get("provider"))) or {})
    input_tokens, output_tokens = call.get("input_tokens"), call.get("output_tokens")
    if not record or not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return {
            "input_cost": None,
            "cached_input_cost": None,
            "output_cost": None,
            "reasoning_cost": None,
            "total_cost": None,
            "currency": catalog.get("comparison_currency"),
            "status": "NOT_EVALUATED_USAGE_UNAVAILABLE",
        }
    cached = max(0, int(call.get("cached_tokens") or 0))
    uncached = max(0, input_tokens - cached)
    native_input = uncached * float(record["input_price_per_million"]) / 1_000_000
    native_cached = cached * float(record["cached_input_price_per_million"]) / 1_000_000
    native_output = output_tokens * float(record["output_price_per_million"]) / 1_000_000
    currency = str(record["currency"])
    comparison = str(catalog.get("comparison_currency") or currency)
    rate = float(dict(catalog.get("rates") or {}).get(currency, 1.0))
    return {
        "input_cost": native_input * rate,
        "cached_input_cost": native_cached * rate,
        "output_cost": native_output * rate,
        "reasoning_cost": 0.0,
        "reasoning_billing": "INCLUDED_IN_OUTPUT_TOKENS_NOT_DOUBLE_COUNTED",
        "total_cost": (native_input + native_cached + native_output) * rate,
        "native_total_cost": native_input + native_cached + native_output,
        "native_currency": currency,
        "currency": comparison,
        "status": "EVALUATED",
    }


def _augment_cost(call: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(call)
    result.update(_call_cost(result, catalog))
    return result


def _group_call_rows(group: Mapping[str, Any], outcomes: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for case in group["cases"]:
        for role in case["call_roles"]:
            rows.append(outcomes[(str(case["case_id"]), str(role))])
    return rows


def _usage_metrics(group: Mapping[str, Any], outcomes: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    rows = _group_call_rows(group, outcomes)
    strong = [row for row in rows if row.get("role") == "strong"]
    cheap = [row for row in rows if row.get("role") == "cheap"]
    successes = int(group["success"])

    def block(selected: list[Mapping[str, Any]]) -> dict[str, Any]:
        states = [_usage_state(row) for row in selected]
        result: dict[str, Any] = {
            "calls": len(selected),
            "known_calls": sum(state == "KNOWN" for state in states),
            "partial_calls": sum(state == "PARTIAL" for state in states),
            "unknown_calls": sum(state == "UNKNOWN" for state in states),
            "usage_completeness_rate": (sum(state == "KNOWN" for state in states) / len(states)) if states else 1.0,
        }
        for field in _TOKEN_FIELDS:
            result[field] = _exact_sum(selected, field)
            result[field + "_observed_lower_bound"] = _known_sum(selected, field)
        return result

    all_block, strong_block, cheap_block = block(rows), block(strong), block(cheap)
    exact_total = all_block["total_tokens"]
    exact_strong = strong_block["total_tokens"]
    exact_strong_input = strong_block["input_tokens"]
    costs = [row.get("cost") for row in rows]
    cost_complete = all(isinstance(value, (int, float)) for value in costs)
    exact_cost = sum(float(value) for value in costs) if cost_complete else None
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    strong_latencies = [float(row.get("latency_ms") or 0.0) for row in strong]
    cheap_latencies = [float(row.get("latency_ms") or 0.0) for row in cheap]
    return {
        "usage": all_block,
        "strong_usage": strong_block,
        "cheap_usage": cheap_block,
        "tokens_per_success": exact_total / successes if exact_total is not None and successes else None,
        "strong_tokens_per_success": exact_strong / successes if exact_strong is not None and successes else None,
        "strong_input_tokens_per_success": exact_strong_input / successes if exact_strong_input is not None and successes else None,
        "strong_calls_per_success": len(strong) / successes if successes else None,
        "cost": exact_cost,
        "cost_currency": next((row.get("cost_currency") for row in rows if row.get("cost_currency")), None),
        "cost_per_success": exact_cost / successes if exact_cost is not None and successes else None,
        "cost_completeness_rate": (sum(isinstance(value, (int, float)) for value in costs) / len(costs)) if costs else 1.0,
        "latency": {
            "total_ms": round(sum(latencies), 3),
            "model_ms": round(sum(latencies), 3),
            "strong_ms": round(sum(strong_latencies), 3),
            "cheap_ms": round(sum(cheap_latencies), 3),
            "deterministic_ms": 0.0,
            "p50_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
            "p95_ms": _percentile(latencies, 0.95),
        },
    }


def _reduction(baseline: float | int | None, candidate: float | int | None) -> float | None:
    if baseline in {None, 0} or candidate is None:
        return None
    return 1.0 - float(candidate) / float(baseline)


def _precision_recall(group: Mapping[str, Any]) -> dict[str, Any]:
    strong_calls = 0
    justified = 0
    required = 0
    covered = 0
    for row in group["cases"]:
        roles = list(row["call_roles"])
        if row["expected_level"] == DecisionLevel.STRONG_MODEL.value:
            required += 1
            covered += int("strong" in roles)
        if "strong" in roles:
            strong_calls += 1
            justified += int(
                row["expected_level"] == DecisionLevel.STRONG_MODEL.value
                or bool(row.get("validator_contained_failure"))
            )
    return {
        "strong_call_precision": justified / strong_calls if strong_calls else None,
        "strong_escalation_recall": covered / required if required else None,
        "justified_strong_calls": justified,
        "strong_required_cases": required,
        "strong_required_covered": covered,
    }


def _router_audit(groups: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    router = DecisionRouter()
    d3_rows = {row["case_id"]: row for row in groups["D3"]["cases"]}
    result = []
    for case in decision_cases():
        route = router.route(case.context)
        row = d3_rows[case.case_id]
        result.append({
            "case_id": case.case_id,
            "operation": case.context.operation,
            "expected_level": case.expected.value,
            "risk_class": route.risk.risk_class.value,
            "selected_executor": row["initial_level"],
            "reason_codes": list(route.reason_codes),
            "validator_result": row["validation"],
            "escalation_event": bool(row.get("validator_contained_failure")),
            "final_result": "ACCEPTED" if row["accepted"] else "REJECTED_OR_FAILED",
        })
    return result


def _break_even(groups: Mapping[str, Mapping[str, Any]], outcomes: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    costs: dict[str, dict[str, float]] = defaultdict(dict)
    case_map = {case.case_id: case for case in decision_cases()}
    for strategy in ("D2", "D3"):
        by_class: dict[str, list[float]] = defaultdict(list)
        for row in groups[strategy]["cases"]:
            expected = case_map[row["case_id"]].expected
            if expected not in {DecisionLevel.CHEAP_MODEL, DecisionLevel.STRONG_MODEL}:
                continue
            selected = [outcomes[(row["case_id"], role)].get("cost") for role in row["call_roles"]]
            if all(isinstance(value, (int, float)) for value in selected):
                by_class[expected.value].append(sum(float(value) for value in selected))
        for level, values in by_class.items():
            costs[strategy][level] = statistics.mean(values)
    required = {
        strategy: {level: costs.get(strategy, {}).get(level) for level in (DecisionLevel.CHEAP_MODEL.value, DecisionLevel.STRONG_MODEL.value)}
        for strategy in ("D2", "D3")
    }
    if any(value is None for strategy in required.values() for value in strategy.values()):
        return {"status": "NOT_EVALUATED_INCOMPLETE_COST", "per_class_cost": required}
    a = required["D3"][DecisionLevel.CHEAP_MODEL.value] - required["D2"][DecisionLevel.CHEAP_MODEL.value]
    b = required["D3"][DecisionLevel.STRONG_MODEL.value] - required["D2"][DecisionLevel.STRONG_MODEL.value]
    denominator = b - a
    threshold = (-a / denominator) if denominator else None
    return {
        "status": "EVALUATED",
        "population": "MODEL_ROUTED_CASES_WITHIN_FROZEN_PHASE_MIX",
        "strong_required_share_break_even": threshold,
        "per_class_cost": required,
        "interpretation": (
            "D3_CHEAPER_BELOW_BREAK_EVEN" if threshold is not None and denominator > 0 else
            "D3_CHEAPER_ABOVE_BREAK_EVEN" if threshold is not None else
            "NO_FINITE_BREAK_EVEN"
        ),
    }


def analyze_closure(
    *,
    previous_receipt_path: pathlib.Path | str,
    previous_budget_path: pathlib.Path | str,
    pricing_catalog: Mapping[str, Any],
    pricing_snapshot_path: pathlib.Path | str,
    product_source_commit: str,
    product_source_tree: str,
    harness_commit: str,
    replacement_path: pathlib.Path | str | None = None,
    repository_root: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    receipt_path = pathlib.Path(previous_receipt_path)
    budget_path = pathlib.Path(previous_budget_path)
    decision = _decision_document(load_document(receipt_path))
    root = pathlib.Path(repository_root) if repository_root else None
    routing = CGKNModelRouting.load(root / "config/provider_profiles/gateway_model_routing.json") if root else CGKNModelRouting(
        ModelRoleConfig("agent", "qwen", timeout_seconds=90, max_output_tokens=7000),
        ModelRoleConfig("worker", "deepseek", timeout_seconds=90, max_output_tokens=6000),
        frozenset({"qwen", "deepseek", "grok"}),
    )
    compatibility = _require_semantic_compatibility(
        decision,
        routing,
        product_source_commit=product_source_commit,
        product_source_tree=product_source_tree,
        repository_root=root,
    )

    original_calls = [_augment_cost(row, pricing_catalog) for row in decision["calls"]]
    outcomes = {(str(row["case_id"]), str(row["role"])): row for row in original_calls}
    replacement_doc = None
    replacement_applied = False
    if replacement_path:
        replacement_doc = load_document(replacement_path)
        replacement = _augment_cost(dict(replacement_doc["replacement_call"]), pricing_catalog)
        original = dict(replacement_doc["original_call"])
        key = (str(original["case_id"]), str(original["role"]))
        frozen = outcomes[key]
        if original.get("prompt_hash") != frozen.get("prompt_hash") or replacement.get("prompt_hash") != frozen.get("prompt_hash"):
            raise ValueError("replacement does not preserve the frozen prompt identity")
        if replacement.get("schema_hash") != frozen.get("schema_hash"):
            raise ValueError("replacement does not preserve the frozen schema identity")
        if replacement.get("usage_status") == "REPORTED" and _usage_state(replacement) == "KNOWN":
            outcomes[key] = replacement
            replacement_applied = True

    cases = decision_cases()
    semantic_groups = {
        strategy: _evaluate_strategy(strategy, cases, outcomes)
        for strategy in ("D0", "D1", "D2", "D3")
    }
    extended_groups = {}
    for strategy, group in semantic_groups.items():
        extended_groups[strategy] = group | _usage_metrics(group, outcomes) | _precision_recall(group)

    original_group_metrics = {}
    original_outcomes = {(str(row["case_id"]), str(row["role"])): row for row in original_calls}
    for strategy, group in decision["groups"].items():
        original_group_metrics[strategy] = dict(group) | _usage_metrics(group, original_outcomes) | _precision_recall(group)

    budget = load_document(budget_path)
    budget_by_case = {str(row.get("case_id")): row for row in budget.get("calls", [])}
    memberships: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name, group in decision["groups"].items():
        for row in group["cases"]:
            for role in row["call_roles"]:
                memberships[(str(row["case_id"]), str(role))].append(name)
    audit = []
    for row in original_calls:
        budget_row = dict(budget_by_case.get(f"{row['case_id']}-{row['role']}") or {})
        audit.append({
            "transport_id": row.get("request_id") or budget_row.get("call_id"),
            "route": row["role"],
            "provider": row.get("provider"),
            "model": row.get("model"),
            "groups": sorted(memberships[(str(row["case_id"]), str(row["role"]))]),
            "case_id": row["case_id"],
            "result_status": row.get("status"),
            "http_status": budget_row.get("http_status"),
            "timeout": row.get("error_class") == "outcome_unknown" and row.get("latency_ms", 0) >= row.get("configured_timeout_seconds", 0) * 1000,
            "truncation": str(row.get("finish_reason") or "").lower() in {"length", "max_tokens"},
            "accepted": row.get("accepted"),
            "usage_state": _usage_state(row),
            **{name: row.get(name) for name in _TOKEN_FIELDS},
            "billing_usage": _call_cost_components(row, pricing_catalog),
            "latency_ms": row.get("latency_ms"),
            "provider_request_id": row.get("request_id"),
            "request_identity": budget_row.get("request_identity"),
            "receipt_completeness": "COMPLETE" if row.get("request_id") and _usage_state(row) == "KNOWN" else "INCOMPLETE",
        })

    d0, d1, d2, d3 = (extended_groups[name] for name in ("D0", "D1", "D2", "D3"))
    comparisons = {
        "D3_vs_D0": {
            "success_rate_gap": d3["success_rate"] - d0["success_rate"],
            "strong_call_reduction": _reduction(d0["strong_calls"], d3["strong_calls"]),
            "strong_input_tokens_per_success_reduction": _reduction(d0["strong_input_tokens_per_success"], d3["strong_input_tokens_per_success"]),
            "strong_total_tokens_per_success_reduction": _reduction(d0["strong_tokens_per_success"], d3["strong_tokens_per_success"]),
            "total_tokens_per_success_reduction": _reduction(d0["tokens_per_success"], d3["tokens_per_success"]),
            "cost_per_success_reduction": _reduction(d0["cost_per_success"], d3["cost_per_success"]),
        },
        "D3_vs_D1": {
            "success_rate_gap": d3["success_rate"] - d1["success_rate"],
            "missed_escalations_removed": d1["missed_escalations"] - d3["missed_escalations"],
            "cost_per_success_delta": (d3["cost_per_success"] - d1["cost_per_success"]) if d3["cost_per_success"] is not None and d1["cost_per_success"] is not None else None,
        },
        "D3_vs_D2": {
            "success_rate_gap": d3["success_rate"] - d2["success_rate"],
            "strong_call_reduction": _reduction(d2["strong_calls"], d3["strong_calls"]),
            "strong_total_tokens_per_success_reduction": _reduction(d2["strong_tokens_per_success"], d3["strong_tokens_per_success"]),
            "cost_per_success_reduction": _reduction(d2["cost_per_success"], d3["cost_per_success"]),
        },
    }

    # Before replacement, the same unknown call appears in both D0 and D3.  The
    # 50% gate can hold only when x <= B - 2A; a negative value proves that no
    # non-negative unknown usage could qualify the frozen workload.
    original_d0 = original_group_metrics["D0"]["strong_usage"]
    original_d3 = original_group_metrics["D3"]["strong_usage"]
    input_break_even = original_d0["input_tokens_observed_lower_bound"] - 2 * original_d3["input_tokens_observed_lower_bound"]
    total_break_even = original_d0["total_tokens_observed_lower_bound"] - 2 * original_d3["total_tokens_observed_lower_bound"]
    sensitivity = {
        "unknown_call": "strong-6/strong",
        "unknown_is_zero_assumed": False,
        "observed_lower_bound": {
            "D0_strong_input_tokens": original_d0["input_tokens_observed_lower_bound"],
            "D3_strong_input_tokens": original_d3["input_tokens_observed_lower_bound"],
            "D0_strong_total_tokens": original_d0["total_tokens_observed_lower_bound"],
            "D3_strong_total_tokens": original_d3["total_tokens_observed_lower_bound"],
        },
        "maximum_unknown_tokens_that_still_meet_50_percent_gate": {
            "input_tokens": input_break_even,
            "total_tokens": total_break_even,
        },
        "gate_possible_for_any_nonnegative_unknown_usage": input_break_even >= 0 and total_break_even >= 0,
    }

    reliability_gate = d3["success_rate"] >= d0["success_rate"] - 0.05
    token_gate = (
        comparisons["D3_vs_D0"]["strong_total_tokens_per_success_reduction"] is not None
        and comparisons["D3_vs_D0"]["strong_total_tokens_per_success_reduction"] >= 0.5
    )
    cost_gate = (
        d3["cost_per_success"] is not None
        and d0["cost_per_success"] is not None
        and d3["cost_per_success"] < d0["cost_per_success"]
    )
    complete_usage = all(group["usage"]["usage_completeness_rate"] == 1.0 for group in extended_groups.values())
    base_gates = (
        reliability_gate
        and token_gate
        and cost_gate
        and d3["critical_stop_correctness"] >= d0["critical_stop_correctness"]
        and d3["missed_escalations"] == 0
        and d3["scope_security_violations"] <= d0["scope_security_violations"]
    )
    if base_gates and complete_usage and d3["cost_per_success"] < d2["cost_per_success"] and d3["success_rate"] >= d2["success_rate"] - 0.05:
        adaptive = "QUALIFIED"
    elif reliability_gate and cost_gate and comparisons["D3_vs_D0"]["strong_call_reduction"] > 0:
        adaptive = "PROVEN_DIRECTIONALLY"
    elif d3["success_rate"] < d0["success_rate"] - 0.05 or (d3["cost_per_success"] is not None and d3["cost_per_success"] > d0["cost_per_success"]):
        adaptive = "HARMFUL"
    else:
        adaptive = "NEUTRAL"
    strong_benefit = "QUALIFIED" if base_gates and complete_usage else "DIRECTIONAL" if reliability_gate and cost_gate else "NOT_PROVEN"

    decision_file = root / "cgkn/application/capability_routing/decision.py" if root else None
    production_loc = None
    if decision_file and decision_file.is_file():
        production_loc = sum(
            1 for line in decision_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    tests = 0
    if root:
        for path in (root / "tests/application/capability_routing").glob("test_*.py"):
            tests += sum(line.startswith("def test_") for line in path.read_text(encoding="utf-8").splitlines())

    body = {
        "kind": "PB027StrongEscalationEvidenceClosure",
        "schema_version": "1.0",
        "analysis_version": PB027_VERSION,
        "product_source_commit": product_source_commit,
        "product_source_tree": product_source_tree,
        "harness_commit": harness_commit,
        "source_compatibility": compatibility,
        "previous_receipt": {
            "path": str(receipt_path),
            "file_sha256": _sha256_file(receipt_path),
            "receipt_hash": decision.get("receipt_hash"),
        },
        "previous_budget_ledger": {"path": str(budget_path), "file_sha256": _sha256_file(budget_path)},
        "pricing_snapshot": {
            "path": str(pricing_snapshot_path),
            "file_sha256": _sha256_file(pathlib.Path(pricing_snapshot_path)),
            "snapshot_hash": pricing_catalog.get("snapshot_hash"),
            "comparison_currency": pricing_catalog.get("comparison_currency"),
            "records": pricing_catalog.get("records"),
        },
        "usage_recovery": {
            "historical_result": "UNRECOVERABLE_NO_RESPONSE_NO_REQUEST_ID_NO_PERSISTED_API_LAB_LOG",
            "replacement_attempted": replacement_doc is not None,
            "replacement_applied_to_semantic_view": replacement_applied,
            "original_operational_failure_preserved": True,
            "replacement_receipt_hash": replacement_doc.get("receipt_hash") if replacement_doc else None,
        },
        "transport_audit": audit,
        "original_operational_groups": original_group_metrics,
        "semantic_groups": extended_groups,
        "router_audit": _router_audit(semantic_groups),
        "comparisons": comparisons,
        "sensitivity": sensitivity,
        "break_even": _break_even(semantic_groups, outcomes),
        "workload": {"total": 24, "deterministic": 6, "cheap_sufficient": 8, "strong_required": 6, "human_stop": 4},
        "per_100_decisions": {
            name: {
                "strong_calls": group["strong_calls"] / 24 * 100,
                "cheap_calls": group["cheap_calls"] / 24 * 100,
                "expected_failures": (24 - group["success"]) / 24 * 100,
                "critical_misses": 4 * (1 - group["critical_stop_correctness"]),
                "estimated_cost": (group["cost"] / 24 * 100) if group["cost"] is not None else None,
                "currency": group["cost_currency"],
            }
            for name, group in extended_groups.items()
        },
        "router_complexity_cost": {
            "production_nonblank_noncomment_loc": production_loc,
            "production_file": "cgkn/application/capability_routing/decision.py",
            "policy_rule_surfaces": 11,
            "test_cases": tests,
            "maximum_model_runtime_hops": 2,
            "maintenance_surface": [
                "risk assessment",
                "initial route policy",
                "validator-driven escalation policy",
                "formal benchmark projection",
            ],
        },
        "qualification": {
            "reliability_gate": reliability_gate,
            "strong_token_reduction_gate": token_gate,
            "cost_per_success_gate": cost_gate,
            "critical_stop_gate": d3["critical_stop_correctness"] >= d0["critical_stop_correctness"],
            "missed_escalation_gate": d3["missed_escalations"] == 0,
            "scope_security_gate": d3["scope_security_violations"] <= d0["scope_security_violations"],
            "usage_complete": complete_usage,
            "STRONG_ESCALATION_BENEFIT": strong_benefit,
            "ADAPTIVE_DECISION_HIERARCHY_BENEFIT": adaptive,
            "should_adaptive_routing_become_default": "YES" if adaptive == "QUALIFIED" else "NOT_YET",
            "should_strong_role_separation_be_collapsed": "NOT_YET",
        },
        "production_semantics_byte_identical": True,
        "threshold_tuning": "NOT_PERFORMED",
        "contains_credentials": False,
        "raw_provider_text_stored": False,
    }
    return body | {"receipt_hash": stable_hash(body)}
