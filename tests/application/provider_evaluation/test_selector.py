from __future__ import annotations

import json

import pytest

from cgkn.application.provider_evaluation import (
    BenchmarkBudget,
    ProviderBenchmarkCase,
    ProviderBenchmarkReceipt,
    ProviderProfileCache,
    ProviderSelector,
    aggregate_profiles,
)


def receipt(
    provider: str,
    task: str,
    case: str,
    *,
    success: bool = True,
    schema: bool = True,
    functional: bool | None = None,
    interface: bool = True,
    scope: bool = True,
    secret_safe: bool = True,
    tokens: int = 100,
    cost: float | str = "UNAVAILABLE",
    latency: int = 100,
) -> ProviderBenchmarkReceipt:
    valid = success if functional is None else functional
    return ProviderBenchmarkReceipt(
        provider_id=provider,
        actual_model=f"{provider}-actual",
        task_class=task,
        benchmark_id=case,
        benchmark_version="suite-v1",
        prompt_hash=f"sha256:{case:0<64}"[:71],
        contract_hash="sha256:" + "c" * 64,
        success=success,
        schema_valid=schema,
        functional_valid=valid,
        interface_valid=interface,
        scope_valid=scope,
        repair_required=task == "worker.repair",
        input_tokens=tokens // 2,
        output_tokens=tokens - tokens // 2,
        total_tokens=tokens,
        cost_estimate=cost,
        wall_time_ms=latency,
        error_class="NONE" if success else "TASK_FAILURE",
        request_ids=(f"request-{provider}-{case}",),
        source_commit="a" * 40,
        gateway_config_hash="sha256:" + "g" * 64,
        secret_safe=secret_safe,
    )


@pytest.mark.happy_path
@pytest.mark.boundary
def test_case_contract_and_profile_cache_key_are_stable() -> None:
    case = ProviderBenchmarkCase(
        case_id="structured-a",
        task_class="structured.output",
        role="worker",
        input_contract={"type": "object"},
        expected_output_contract={"type": "object", "required": ["value"]},
        budget=BenchmarkBudget(30, 1000, 200),
        timeout=30,
        validation=("schema", "unknown_fields"),
        risk="LOW",
        benchmark_version="suite-v1",
        prompt_facts=("value must be lowercase",),
    )
    assert case.contract_hash == case.contract_hash
    profiles = aggregate_profiles(
        [receipt("qwen", "structured.output", "a"), receipt("qwen", "structured.output", "b")],
        benchmark_suite_hash="sha256:" + "s" * 64,
    )
    assert profiles[0].eligible is True
    assert profiles[0].cache_key == (
        "qwen", "qwen-actual", "sha256:" + "g" * 64,
        "sha256:" + "s" * 64, "structured.output", "provider-selection-v1",
    )


@pytest.mark.negative
@pytest.mark.security
@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"schema": False, "success": False}, "SCHEMA_COMPLIANCE_BELOW_100_PERCENT"),
        ({"scope": False, "success": False}, "SCOPE_VIOLATION"),
        ({"interface": False, "success": False}, "INTERFACE_VIOLATION"),
        ({"secret_safe": False, "success": False}, "SECRET_OR_ERROR_LEAKAGE"),
    ],
)
def test_hard_gate_rejects_integrity_failures(mutation, reason) -> None:
    rows = [receipt("qwen", "worker.codegen", "a"), receipt("qwen", "worker.codegen", "b", **mutation)]
    profile = aggregate_profiles(rows, benchmark_suite_hash="sha256:" + "s" * 64)[0]
    assert profile.eligible is False
    assert reason in profile.ineligible_reasons


@pytest.mark.negative
@pytest.mark.boundary
def test_fewer_than_two_samples_is_ineligible() -> None:
    profile = aggregate_profiles(
        [receipt("qwen", "worker.codegen", "a")],
        benchmark_suite_hash="sha256:" + "s" * 64,
    )[0]
    assert profile.eligible is False
    assert profile.ineligible_reasons == ("INSUFFICIENT_SAMPLES",)


@pytest.mark.happy_path
@pytest.mark.determinism
def test_reliability_wins_over_cost_and_latency() -> None:
    rows = [
        receipt("qwen", "worker.codegen", "a", cost=1.0, tokens=200, latency=300),
        receipt("qwen", "worker.codegen", "b", cost=1.0, tokens=200, latency=300),
        receipt("deepseek", "worker.codegen", "a", success=False, functional=False, cost=0.01, tokens=20, latency=10),
        receipt("deepseek", "worker.codegen", "b", cost=0.01, tokens=20, latency=10),
    ]
    selector = ProviderSelector(aggregate_profiles(rows, benchmark_suite_hash="sha256:" + "s" * 64))
    decision = selector.select("worker.codegen")
    assert decision.selected_provider == "qwen"
    assert decision.eligible_providers == ("deepseek", "qwen")
    assert "functional=1.000" in decision.reason


@pytest.mark.happy_path
@pytest.mark.determinism
def test_task_specific_winners_and_unknown_cost_renormalization() -> None:
    rows = []
    for task, winner in (("agent.composition", "qwen"), ("worker.codegen", "deepseek"), ("worker.repair", "grok")):
        for provider in ("qwen", "deepseek", "grok"):
            for case in ("a", "b"):
                rows.append(receipt(
                    provider,
                    task,
                    case,
                    success=provider == winner or case == "a",
                    functional=provider == winner or case == "a",
                    cost="UNAVAILABLE",
                    tokens=80 if provider == winner else 60,
                    latency=90 if provider == winner else 50,
                ))
    selector = ProviderSelector(aggregate_profiles(rows, benchmark_suite_hash="sha256:" + "s" * 64))
    assert selector.select("agent.composition").selected_provider == "qwen"
    assert selector.select("worker.codegen").selected_provider == "deepseek"
    assert selector.select("worker.repair").selected_provider == "grok"


@pytest.mark.happy_path
@pytest.mark.security
@pytest.mark.roundtrip
def test_frozen_snapshot_is_immutable_credential_free_and_write_once(tmp_path) -> None:
    rows = []
    for task in ("agent.composition", "worker.codegen"):
        rows.extend([receipt("qwen", task, "a"), receipt("qwen", task, "b")])
    snapshot = ProviderSelector(
        aggregate_profiles(rows, benchmark_suite_hash="sha256:" + "s" * 64)
    ).freeze("run-1", ("agent.composition", "worker.codegen"))
    assert snapshot.fallback == "deny"
    with pytest.raises(TypeError):
        snapshot.routes["worker.codegen"] = "grok"  # type: ignore[index]
    path = snapshot.write_once(tmp_path / "provider-routing.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["contains_credentials"] is False
    assert "token" not in json.dumps(value).lower()
    with pytest.raises(FileExistsError):
        snapshot.write_once(path)


@pytest.mark.negative
def test_selector_fails_closed_without_eligible_provider() -> None:
    rows = [receipt("qwen", "worker.codegen", "a")]
    selector = ProviderSelector(aggregate_profiles(rows, benchmark_suite_hash="sha256:" + "s" * 64))
    with pytest.raises(RuntimeError, match="PROVIDER_SELECTION_NEEDS_REWORK"):
        selector.select("worker.codegen")


@pytest.mark.roundtrip
@pytest.mark.determinism
def test_profile_cache_reuses_only_the_exact_material_key(tmp_path) -> None:
    profile = aggregate_profiles(
        [receipt("qwen", "worker.codegen", "a"), receipt("qwen", "worker.codegen", "b")],
        benchmark_suite_hash="sha256:" + "s" * 64,
    )[0]
    cache = ProviderProfileCache(tmp_path / "profiles.json")
    cache.write((profile,))
    assert cache.find(profile.cache_key).profile_hash == profile.profile_hash
    changed_suite = list(profile.cache_key)
    changed_suite[3] = "sha256:" + "x" * 64
    assert cache.find(tuple(changed_suite)) is None
