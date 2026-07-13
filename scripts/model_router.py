from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

try:
    from scripts import provider_transport
except ModuleNotFoundError:  # pragma: no cover
    import provider_transport  # type: ignore


DETERMINISTIC_TASKS = {
    "schema_validation",
    "dependency_gate",
    "ownership_collision",
    "ledger_transition",
    "package_inventory",
    "secret_scan",
    "screenshot_hash_duplicate",
    "evidence_reference_validation",
    "verdict_propagation",
    "cache_fingerprint",
    "budget_reservation",
}

LOCAL_TASKS = {
    "log_summary",
    "context_compression",
    "task_classification",
    "failure_classification",
    "experience_query_rewrite",
    "finding_dedup",
    "file_task_matching",
    "low_risk_review",
    "milestone_summary",
}

API_HIGH_VALUE = {
    "requirement_decision",
    "architecture",
    "high_risk_leaf",
    "complex_interface",
    "unknown_semantic_defect",
    "double_loop_replan",
    "customer_proxy",
    "complex_repair",
    "final_high_risk_review",
}


def utc_now() -> str:
    return datetime.now().astimezone().isoformat()


def append_jsonl(path: str | pathlib.Path, doc: dict[str, Any]) -> None:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")


def route_task(request: dict[str, Any]) -> dict[str, Any]:
    task_type = str(request.get("task_type", ""))
    risk = str(request.get("risk", "low")).lower()
    novelty = float(request.get("novelty", 0.0) or 0.0)
    complexity = float(request.get("complexity", 0.0) or 0.0)
    previous_failures = int(request.get("previous_failures", 0) or 0)
    experience_confidence = float(request.get("experience_confidence", 0.0) or 0.0)
    local_ready = bool(request.get("local_model_readiness"))
    local_confidence = float(request.get("local_model_confidence", 0.0) or 0.0)
    api_ready = bool(request.get("api_readiness"))
    api_budget = str(request.get("api_budget", "low"))
    circuit_state = str(request.get("circuit_state", "closed"))
    context_size = int(request.get("context_size", 0) or 0)
    required_output_type = str(request.get("required_output_type", "text"))

    reasons: list[str] = []
    fallback = "none"
    selected_route = "deterministic"
    selected_model = "rules"

    if task_type in DETERMINISTIC_TASKS:
        reasons.append("stable_rule_task")
    elif task_type in API_HIGH_VALUE or risk == "high" or complexity >= 0.75 or novelty >= 0.75:
        reasons.append("high_value_or_high_risk")
        if api_ready and api_budget != "off" and circuit_state != "open":
            selected_route = "api_model"
            selected_model = str(request.get("api_model", "provider"))
        else:
            selected_route = "deterministic"
            selected_model = "blocked_api_fallback"
            fallback = "BLOCKED_PROVIDER" if not api_ready or circuit_state == "open" else "BLOCKED_API_BUDGET"
    elif task_type in LOCAL_TASKS:
        reasons.append("local_model_suitable")
        if local_ready and local_confidence >= 0.45:
            selected_route = "local_model"
            selected_model = str(request.get("local_model", "local"))
        else:
            selected_route = "deterministic"
            selected_model = "local_unavailable_fallback"
            fallback = "BLOCKED_LOCAL_MODEL" if not local_ready else "LOW_LOCAL_CONFIDENCE"
    elif previous_failures >= 2:
        reasons.append("repeated_failure_escalation")
        if api_ready and api_budget != "off" and circuit_state != "open":
            selected_route = "api_model"
            selected_model = str(request.get("api_model", "provider"))
        elif local_ready:
            selected_route = "local_model"
            selected_model = str(request.get("local_model", "local"))
            fallback = "api_unavailable_local_retry"
        else:
            selected_route = "deterministic"
            selected_model = "manager_replan_required"
            fallback = "DOUBLE_LOOP_REPLAN"
    elif experience_confidence >= 0.7 and local_ready and task_type in LOCAL_TASKS:
        selected_route = "local_model"
        selected_model = str(request.get("local_model", "local"))
        reasons.append("high_confidence_experience_local")
    else:
        selected_route = "deterministic"
        selected_model = "rules"
        reasons.append("default_low_risk_rule_path")

    if selected_route == "api_model":
        profile = provider_transport.request_type_policy(str(request.get("request_type", "leaf_generation")), api_budget)
        context_budget = int(profile["max_prompt_chars"])
        output_budget = int(profile["max_output_tokens"])
    elif selected_route == "local_model":
        context_budget = min(max(1000, context_size), 6000)
        output_budget = 900
    else:
        context_budget = 0
        output_budget = 0

    return {
        "created_at": utc_now(),
        "selected_route": selected_route,
        "selected_model": selected_model,
        "reason_codes": reasons,
        "context_budget": context_budget,
        "output_budget": output_budget,
        "fallback": fallback,
        "blocking_policy": "external_failures_do_not_penalize_agent",
        "verification_policy": "nearest_test_then_review" if selected_route != "deterministic" else "deterministic_rule_check",
        "required_output_type": required_output_type,
    }


def record_decision(path: str | pathlib.Path, request: dict[str, Any]) -> dict[str, Any]:
    decision = route_task(request)
    append_jsonl(path, {"request": request, "decision": decision})
    return decision


def provider_consumption_status(provider_events: list[dict[str, Any]], evidence_events: list[dict[str, Any]]) -> dict[str, Any]:
    consumed_ids: set[str] = set()
    for event in evidence_events:
        for request_id in event.get("provider_request_ids", []) or []:
            consumed_ids.add(str(request_id))
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if data.get("consumed_provider_request_id"):
            consumed_ids.add(str(data["consumed_provider_request_id"]))
    unused = []
    consumed = []
    for event in provider_events:
        request_id = str(event.get("request_id", ""))
        if not request_id:
            continue
        row = {
            "request_id": request_id,
            "response_hash": event.get("response_hash", ""),
            "produced_artifacts": event.get("produced_artifacts", []),
            "consumed_by": event.get("consumed_by", ""),
        }
        if request_id in consumed_ids or event.get("consumed_by"):
            consumed.append(row)
        else:
            unused.append(row)
    return {
        "status": "PASS" if not unused else "PASS_WITH_LIMITS",
        "consumed": consumed,
        "unused_provider_outputs": unused,
        "unused_count": len(unused),
    }
