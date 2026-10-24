from __future__ import annotations

import json

from cgkn.application.capability_routing.formal import (
    FORMAL_MAX_OUTPUT_TOKENS,
    FORMAL_MAX_UNIQUE_LIVE_CALLS,
    _failure_usage,
    load_pricing_catalog,
    run_formal_decision,
    run_formal_search,
)
from cgkn.providers import (
    CGKNModelRouting,
    GatewayCompletionError,
    ModelRoleConfig,
    ProviderCompletion,
)


class FakePairedClient:
    def __init__(self, *, cheap_wrong_operation: str = "", report_usage: bool = True) -> None:
        self.cheap_wrong_operation = cheap_wrong_operation
        self.report_usage = report_usage
        self.calls: list[dict] = []
        self.bindings: list[tuple[str, str, str]] = []

    def bind_run(self, run_id: str, case_id: str, *, budget_purpose: str = "") -> "FakePairedClient":
        self.bindings.append((run_id, case_id, budget_purpose))
        return self

    def complete(self, *, system, user, schema_name, schema, config):
        payload = json.loads(user)
        operation = payload["case"]["context"]["operation"]
        options = payload["task"]["allowed_answers"]
        selected = options[1] if config.role == "worker" and operation == self.cheap_wrong_operation else options[0]
        self.calls.append({
            "system": system,
            "payload": payload,
            "schema_name": schema_name,
            "schema": schema,
            "config": config,
        })
        usage = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110} if self.report_usage else {}
        return ProviderCompletion(
            json.dumps({"decision": selected}),
            f"{config.model}-actual",
            f"request-{len(self.calls)}",
            usage,
            1,
            {"final_status": "ACCEPTED", "selected_candidate_index": 0},
            {"finish_reason": "stop"},
        )


class EvidenceFailureClient(FakePairedClient):
    def complete(self, *, system, user, schema_name, schema, config):
        payload = json.loads(user)
        operation = payload["case"]["context"]["operation"]
        if config.role == "worker" and operation == "PATCH_REVERSIBLE_FILE":
            self.calls.append({
                "system": system,
                "payload": payload,
                "schema_name": schema_name,
                "schema": schema,
                "config": config,
            })
            raise GatewayCompletionError(
                "PROVIDER_SCHEMA_FAILURE",
                "PROVIDER_SCHEMA_FAILURE",
                evidence={
                    "model": "deepseek-actual",
                    "request_id": "failed-request-1",
                    "finish_reason": "stop",
                    "transport_attempts": 1,
                    "transport_attempts_detail": [
                        {"attempt_id": "attempt-1", "status": "COMPLETED", "elapsed_ms": 12}
                    ],
                    "usage_status": "REPORTED",
                    "usage": {
                        "input_tokens": 101,
                        "output_tokens": 9,
                        "total_tokens": 110,
                    },
                    "reasoning_tokens": 4,
                    "cached_tokens": 3,
                    "contains_credentials": False,
                },
            )
        return super().complete(
            system=system, user=user, schema_name=schema_name, schema=schema, config=config
        )


def _routing() -> CGKNModelRouting:
    return CGKNModelRouting(
        ModelRoleConfig("agent", "qwen", timeout_seconds=90, max_output_tokens=7000),
        ModelRoleConfig("worker", "deepseek", timeout_seconds=90, max_output_tokens=6000),
        frozenset({"qwen", "deepseek", "grok"}),
    )


def _run(client: FakePairedClient):
    return run_formal_decision(
        client=client,
        routing=_routing(),
        source_commit="a" * 40,
        source_tree="b" * 40,
        run_id="formal-test",
    )


def test_formal_paired_execution_uses_28_real_calls_without_weakening_strategies() -> None:
    client = FakePairedClient()
    receipt = _run(client)
    assert len(client.calls) == FORMAL_MAX_UNIQUE_LIVE_CALLS == 28
    assert len(client.bindings) == 28
    assert all(row[2] == "BENCHMARK" for row in client.bindings)
    assert receipt["paired_execution"]["unique_live_calls"] == 28
    assert receipt["paired_execution"]["avoided_redundant_calls"] == 28
    assert len(receipt["case_manifest"]) == 24
    assert receipt["status"] == "COMPLETE"
    assert receipt["contains_credentials"] is False
    assert receipt["raw_provider_text_stored"] is False

    d0, d1, d2, d3 = (receipt["groups"][name] for name in ("D0", "D1", "D2", "D3"))
    assert (d0["deterministic_resolutions"], d0["strong_calls"], d0["cheap_calls"]) == (6, 14, 0)
    assert (d1["deterministic_resolutions"], d1["strong_calls"], d1["cheap_calls"]) == (6, 0, 14)
    assert (d2["deterministic_resolutions"], d2["strong_calls"], d2["cheap_calls"]) == (6, 8, 6)
    assert (d3["deterministic_resolutions"], d3["strong_calls"], d3["cheap_calls"]) == (6, 6, 8)
    assert all(row["success"] == 24 for row in (d0, d1, d2, d3))
    assert d0["false_escalations"] == 8
    assert d1["missed_escalations"] == 6
    assert d2["false_escalations"] == 4
    assert d2["missed_escalations"] == 2
    assert d3["false_escalations"] == d3["missed_escalations"] == 0
    assert all(row["critical_stop_correctness"] == 1.0 for row in (d0, d1, d2, d3))
    assert all(call["config"].max_output_tokens == FORMAL_MAX_OUTPUT_TOKENS for call in client.calls)
    assert all(call["payload"]["validator"]["hidden_answer_not_provided"] is True for call in client.calls)
    assert all(call["schema"]["required"] == ["decision"] for call in client.calls)
    assert all(set(call["schema"]["properties"]) == {"decision"} for call in client.calls)
    assert all("exactly one field: decision" in call["system"] for call in client.calls)


def test_d3_validator_contains_cheap_failure_and_escalates_once() -> None:
    receipt = _run(FakePairedClient(cheap_wrong_operation="PATCH_REVERSIBLE_FILE"))
    d1 = receipt["groups"]["D1"]
    d2 = receipt["groups"]["D2"]
    d3 = receipt["groups"]["D3"]
    assert d1["success"] == 23
    assert d2["success"] == 23
    assert d3["success"] == 24
    assert d3["cheap_calls"] == 8
    assert d3["strong_calls"] == 7
    assert d3["validator_contained_failures"] == 1
    row = next(item for item in d3["cases"] if item["case_id"] == "cheap-5")
    assert row["call_roles"] == ["cheap", "strong"]
    assert row["validation"] == "PASS_AFTER_STRONG_ESCALATION"


def test_unknown_usage_remains_null_and_cost_is_not_invented() -> None:
    receipt = _run(FakePairedClient(report_usage=False))
    for group in receipt["groups"].values():
        assert group["total_tokens"] is None
        assert group["cost"] is None
        assert group["cost_status"] == "NOT_EVALUATED_EXACT_PRICING_UNAVAILABLE"
    assert all(call["usage_status"] == "UNREPORTED" for call in receipt["calls"])
    failed_usage = _failure_usage({})
    assert failed_usage["usage_status"] == "UNKNOWN_AFTER_CALL_FAILURE"
    assert failed_usage["input_tokens"] is None
    assert failed_usage["output_tokens"] is None


def test_failed_selection_preserves_receipt_metadata_and_is_priced_when_usage_is_known(tmp_path) -> None:
    records = {
        "strong.json": {
            "provider": "qwen", "model": "qwen-actual",
            "input_price_per_million": 10.0, "cached_input_price_per_million": 5.0,
            "output_price_per_million": 20.0, "reasoning_price_per_million": 20.0,
            "currency": "CNY", "unit": "million_tokens",
            "captured_at": "2026-10-24T00:00:00Z", "source": "provider_billing_config:test",
        },
        "cheap.json": {
            "provider": "deepseek", "model": "deepseek-actual",
            "input_price_per_million": 1.0, "cached_input_price_per_million": 0.5,
            "output_price_per_million": 2.0, "reasoning_price_per_million": 2.0,
            "currency": "CNY", "unit": "million_tokens",
            "captured_at": "2026-10-24T00:00:00Z", "source": "provider_billing_config:test",
        },
    }
    for name, value in records.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    index = {
        "kind": "CGNKOfficialModelPricingSnapshot",
        "strong": "strong.json", "cheap": "cheap.json",
        "captured_at": "2026-10-24T00:00:00Z",
    }
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(index), encoding="utf-8")

    receipt = run_formal_decision(
        client=EvidenceFailureClient(), routing=_routing(),
        source_commit="a" * 40, source_tree="b" * 40,
        run_id="formal-failure-evidence-test",
        pricing_catalog=load_pricing_catalog(path),
    )
    failed = next(
        call for call in receipt["calls"]
        if call["case_id"] == "cheap-5" and call["role"] == "cheap"
    )
    assert failed["status"] == "CALL_FAILED"
    assert failed["model"] == "deepseek-actual"
    assert failed["request_id"] == "failed-request-1"
    assert failed["finish_reason"] == "stop"
    assert failed["transport_attempts"] == 1
    assert failed["transport_attempts_detail"] == [
        {"attempt_id": "attempt-1", "status": "COMPLETED", "elapsed_ms": 12}
    ]
    assert (failed["input_tokens"], failed["output_tokens"], failed["total_tokens"]) == (101, 9, 110)
    assert (failed["cached_tokens"], failed["reasoning_tokens"]) == (3, 4)
    assert failed["usage_status"] == "REPORTED"
    assert failed["cost_status"] == "EVALUATED"
    assert failed["cost"] > 0


def test_formal_search_binds_integrated_source_and_required_scales() -> None:
    receipt = run_formal_search(source_commit="c" * 40, source_tree="d" * 40)
    assert receipt["formal_integrated_source"] is True
    assert receipt["source_commit"] == "c" * 40
    assert receipt["source_tree"] == "d" * 40
    assert receipt["same_registry_for_full_and_topk"] is True
    assert receipt["result"]["real_registry"]["capability_count"] > 0
    assert set(receipt["result"]["synthetic"]) == {"100", "500", "1000"}
    assert receipt["synthetic_is_product_evidence"] is False
    assert receipt["comparison"]["selection_success_delta_full_vs_topk"] == 0.0
    assert receipt["comparison"]["synthetic_min_context_reduction_ratio"] > 0.9
    assert receipt["comparison"]["synthetic_min_ineligible_rejection_rate"] == 1.0
    assert receipt["comparison"]["capability_search_scaling_benefit"] == "PROVEN_FOR_SYNTHETIC_SCALING_ONLY"


def test_formal_routes_must_be_distinct_and_fallback_denied() -> None:
    same = CGKNModelRouting(
        ModelRoleConfig("agent", "qwen"),
        ModelRoleConfig("worker", "qwen"),
        frozenset({"qwen"}),
    )
    try:
        run_formal_decision(
            client=FakePairedClient(), routing=same, source_commit="a" * 40, source_tree="b" * 40
        )
    except ValueError as exc:
        assert "distinct qualified routes" in str(exc)
    else:
        raise AssertionError("same Provider route must not produce a formal strong/cheap comparison")


def test_exact_official_pricing_enables_cost_conclusion(tmp_path) -> None:
    records = {
        "strong.json": {
            "provider": "qwen",
            "model": "qwen-actual",
            "input_price_per_million": 10.0,
            "cached_input_price_per_million": 5.0,
            "output_price_per_million": 20.0,
            "reasoning_price_per_million": 20.0,
            "currency": "CNY",
            "unit": "million_tokens",
            "captured_at": "2026-10-24T00:00:00Z",
            "source": "https://example.invalid/official-qwen-pricing",
        },
        "cheap.json": {
            "provider": "deepseek",
            "model": "deepseek-actual",
            "input_price_per_million": 1.0,
            "cached_input_price_per_million": 0.5,
            "output_price_per_million": 2.0,
            "reasoning_price_per_million": 2.0,
            "currency": "CNY",
            "unit": "million_tokens",
            "captured_at": "2026-10-24T00:00:00Z",
            "source": "provider_billing_config:test-fixture",
        },
    }
    for name, value in records.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    index = {
        "kind": "CGNKOfficialModelPricingSnapshot",
        "strong": "strong.json",
        "cheap": "cheap.json",
        "captured_at": "2026-10-24T00:00:00Z",
    }
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(index), encoding="utf-8")
    pricing = load_pricing_catalog(path)
    receipt = run_formal_decision(
        client=FakePairedClient(),
        routing=_routing(),
        source_commit="a" * 40,
        source_tree="b" * 40,
        run_id="formal-priced-test",
        pricing_catalog=pricing,
    )
    assert receipt["groups"]["D0"]["cost_status"] == "EVALUATED"
    assert receipt["groups"]["D3"]["cost_status"] == "EVALUATED"
    assert receipt["groups"]["D3"]["cost_per_success"] < receipt["groups"]["D0"]["cost_per_success"]
    assert receipt["comparison"]["cost_conclusion"] == "EVALUATED"
    assert receipt["comparison"]["adaptive_decision_hierarchy_benefit"] == "PROVEN_DIRECTIONALLY"

