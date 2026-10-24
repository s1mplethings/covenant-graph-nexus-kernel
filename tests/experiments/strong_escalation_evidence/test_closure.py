from __future__ import annotations

import json

import pytest

from cgkn.application.capability_routing.contracts import stable_hash
from cgkn.application.capability_routing.formal import (
    _call_cost,
    load_pricing_catalog,
    run_formal_decision,
)
from cgkn.providers import CGKNModelRouting, ModelRoleConfig
from experiments.strong_escalation_evidence.closure import analyze_closure, run_single_replacement
from tests.application.capability_routing.test_formal import FakePairedClient


def _routing() -> CGKNModelRouting:
    return CGKNModelRouting(
        ModelRoleConfig("agent", "qwen", timeout_seconds=90, max_output_tokens=7000),
        ModelRoleConfig("worker", "deepseek", timeout_seconds=90, max_output_tokens=6000),
        frozenset({"qwen", "deepseek", "grok"}),
    )


def _pricing(tmp_path):
    for provider, model, input_price, output_price in (
        ("qwen", "qwen-actual", 12.0, 36.0),
        ("deepseek", "deepseek-actual", 1.0, 2.0),
    ):
        (tmp_path / f"{provider}.json").write_text(json.dumps({
            "provider": provider,
            "model": model,
            "input_price_per_million": input_price,
            "cached_input_price_per_million": input_price / 2,
            "output_price_per_million": output_price,
            "reasoning_price_per_million": output_price,
            "currency": "CNY",
            "unit": "million_tokens",
            "captured_at": "2026-10-24T00:00:00Z",
            "source": "provider_billing_config:test",
        }), encoding="utf-8")
    index = tmp_path / "pricing.json"
    index.write_text(json.dumps({
        "kind": "CGNKOfficialModelPricingSnapshot",
        "strong": "qwen.json",
        "cheap": "deepseek.json",
        "captured_at": "2026-10-24T00:00:00Z",
    }), encoding="utf-8")
    return index, load_pricing_catalog(index)


def _fixture(tmp_path):
    product_commit, product_tree = "a" * 40, "b" * 40
    pricing_path, pricing = _pricing(tmp_path)
    decision = run_formal_decision(
        client=FakePairedClient(), routing=_routing(), source_commit=product_commit,
        source_tree=product_tree, run_id="pb027-fixture", pricing_catalog=pricing,
    )
    document = {"decision": decision}
    receipt = tmp_path / "formal.json"
    receipt.write_text(json.dumps(document), encoding="utf-8")
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"calls": []}), encoding="utf-8")
    return document, receipt, budget, pricing_path, pricing, product_commit, product_tree


def test_audit_reports_complete_group_metrics_and_qualification(tmp_path) -> None:
    _, receipt, budget, pricing_path, pricing, product_commit, product_tree = _fixture(tmp_path)
    result = analyze_closure(
        previous_receipt_path=receipt,
        previous_budget_path=budget,
        pricing_catalog=pricing,
        pricing_snapshot_path=pricing_path,
        product_source_commit=product_commit,
        product_source_tree=product_tree,
        harness_commit="c" * 40,
    )
    assert len(result["transport_audit"]) == 28
    assert all(row["usage_state"] == "KNOWN" for row in result["transport_audit"])
    assert all(group["usage"]["usage_completeness_rate"] == 1.0 for group in result["semantic_groups"].values())
    assert result["semantic_groups"]["D3"]["strong_call_precision"] == 1.0
    assert result["semantic_groups"]["D3"]["strong_escalation_recall"] == 1.0
    assert result["qualification"]["critical_stop_gate"] is True


def test_unknown_usage_stays_unknown_and_sensitivity_never_invents_zero(tmp_path) -> None:
    document, receipt, budget, pricing_path, pricing, product_commit, product_tree = _fixture(tmp_path)
    call = next(row for row in document["decision"]["calls"] if row["case_id"] == "strong-6" and row["role"] == "strong")
    for field in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens"):
        call[field] = None
    call.update({"status": "CALL_FAILED", "accepted": False, "usage_status": "UNKNOWN_AFTER_CALL_FAILURE", "error_class": "outcome_unknown", "request_id": None, "model": None})
    call.update(_call_cost(call, pricing))
    document["decision"]["groups"] = run_formal_decision(
        client=FakePairedClient(report_usage=False), routing=_routing(), source_commit=product_commit,
        source_tree=product_tree, run_id="unknown-groups",
    )["groups"]
    receipt.write_text(json.dumps(document), encoding="utf-8")
    result = analyze_closure(
        previous_receipt_path=receipt,
        previous_budget_path=budget,
        pricing_catalog=pricing,
        pricing_snapshot_path=pricing_path,
        product_source_commit=product_commit,
        product_source_tree=product_tree,
        harness_commit="c" * 40,
    )
    audited = next(row for row in result["transport_audit"] if row["case_id"] == "strong-6" and row["route"] == "strong")
    assert audited["usage_state"] == "UNKNOWN"
    assert audited["total_tokens"] is None
    assert result["original_operational_groups"]["D0"]["strong_usage"]["total_tokens"] is None
    assert result["sensitivity"]["unknown_is_zero_assumed"] is False


def test_replacement_requires_transport_failure_and_preserves_prompt_identity(tmp_path) -> None:
    document, *_ = _fixture(tmp_path)
    original = next(row for row in document["decision"]["calls"] if row["case_id"] == "strong-6" and row["role"] == "strong")
    original.update({"status": "CALL_FAILED", "accepted": False, "error_class": "outcome_unknown"})
    result = run_single_replacement(
        client=FakePairedClient(), routing=_routing(), previous_receipt=document,
        product_source_commit="a" * 40, product_source_tree="b" * 40,
        harness_commit="c" * 40, run_id="replacement-test",
    )
    assert result["original_call"]["status"] == "CALL_FAILED"
    assert result["replacement_call"]["status"] == "PASS"
    assert result["replacement_call"]["prompt_hash"] == result["original_call"]["prompt_hash"]
    assert result["replacement_call"]["schema_hash"] == result["original_call"]["schema_hash"]


def test_replacement_refuses_semantic_failure(tmp_path) -> None:
    document, *_ = _fixture(tmp_path)
    original = next(row for row in document["decision"]["calls"] if row["case_id"] == "strong-6" and row["role"] == "strong")
    original.update({"status": "VALIDATOR_REJECTED", "accepted": False, "error_class": "semantic"})
    with pytest.raises(ValueError, match="provider call failure"):
        run_single_replacement(
            client=FakePairedClient(), routing=_routing(), previous_receipt=document,
            product_source_commit="a" * 40, product_source_tree="b" * 40,
            harness_commit="c" * 40, run_id="forbidden",
        )


def test_receipt_hash_is_stable_for_identical_inputs(tmp_path) -> None:
    _, receipt, budget, pricing_path, pricing, product_commit, product_tree = _fixture(tmp_path)
    kwargs = dict(
        previous_receipt_path=receipt,
        previous_budget_path=budget,
        pricing_catalog=pricing,
        pricing_snapshot_path=pricing_path,
        product_source_commit=product_commit,
        product_source_tree=product_tree,
        harness_commit="c" * 40,
    )
    first = analyze_closure(**kwargs)
    second = analyze_closure(**kwargs)
    assert first == second
    assert first["receipt_hash"] == stable_hash({key: value for key, value in first.items() if key != "receipt_hash"})
