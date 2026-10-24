from __future__ import annotations

from cgkn.application.capability_routing.benchmarks import decision_cases, run_decision_discovery, run_discovery, run_search_discovery
from cgkn.application.capability_routing.contracts import DecisionLevel


def test_decision_fixture_has_required_24_case_distribution() -> None:
    cases = decision_cases()
    assert len(cases) == 24
    assert sum(item.expected is DecisionLevel.DETERMINISTIC for item in cases) == 6
    assert sum(item.expected is DecisionLevel.CHEAP_MODEL for item in cases) == 8
    assert sum(item.expected is DecisionLevel.STRONG_MODEL for item in cases) == 6
    assert sum(item.expected is DecisionLevel.HUMAN_STOP for item in cases) == 4
    for item in cases:
        serialized = item.as_dict()
        assert serialized["request"]
        assert "candidate_capabilities" in serialized
        assert "available_inputs" in serialized
        assert serialized["required_effect"]
        assert serialized["qualification"] in {"QUALIFIED", "UNQUALIFIED"}
        assert serialized["expected_validator"] in {"AVAILABLE", "UNAVAILABLE"}


def test_adaptive_discovery_routes_all_cases_without_case_id_rules() -> None:
    result = run_decision_discovery()
    assert result["groups"]["D3"]["routing_accuracy"] == 1.0
    assert result["groups"]["D3"]["deterministic"] == 6
    assert result["groups"]["D3"]["cheap"] == 8
    assert result["groups"]["D3"]["strong"] == 6
    assert result["groups"]["D3"]["human_stop"] == 4
    assert result["groups"]["D3"]["false_escalations"] == 0
    assert result["groups"]["D3"]["missed_escalations"] == 0
    assert result["groups"]["D3"]["critical_stop_correctness"] == 1.0
    assert result["discovery_only"] is True


def test_discovery_baselines_preserve_their_declared_nonadaptive_definitions() -> None:
    result = run_decision_discovery()
    assert result["groups"]["D0"]["strong"] == 20
    assert result["groups"]["D1"]["cheap"] == 20
    assert result["groups"]["D2"]["deterministic"] == 0


def test_search_discovery_covers_real_and_100_500_1000_synthetic_scales() -> None:
    result = run_search_discovery()
    assert result["real_registry"]["capability_count"] > 0
    assert result["real_registry"]["top1_accuracy"] == 1.0
    assert result["real_registry"]["benefit"] == "NOT_YET_NEEDED_AT_CURRENT_SCALE"
    assert set(result["synthetic"]) == {"100", "500", "1000"}
    for row in result["synthetic"].values():
        assert row["top1_accuracy"] == 1.0
        assert row["top3_recall"] == 1.0
        assert row["context_reduction_ratio"] > 0.9
    assert result["synthetic_is_product_evidence"] is False


def test_combined_discovery_receipt_is_secret_safe_and_explicitly_nonformal() -> None:
    receipt = run_discovery()
    assert receipt["contains_credentials"] is False
    assert receipt["formal_d0_d3_required_on_integrated_source"] is True
    assert receipt["benchmark_hash"].startswith("sha256:")
    assert receipt["model_config_hash"].startswith("sha256:")
