from __future__ import annotations

import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "benchmarks" / "mvp_decision_efficiency" / "benchmark_contract.json"


def test_decision_efficiency_contract_targets_brain_calls_and_real_success() -> None:
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert value["modes"] == ["direct_agent", "cgkn_delegated"]
    assert "functional_success" in value["required_metrics"]
    assert "high_capability_agent_calls" in value["required_metrics"]
    assert value["first_gate"]["requires_real_project"] is True
    assert value["first_gate"]["requires_cgkn_functional_success"] is True
    assert value["first_gate"]["requires_fewer_high_capability_agent_calls"] is True
    assert value["first_gate"]["repair_scope"] == "affected_subgraph_only"


def test_scale_and_soak_are_not_first_gate_authorities() -> None:
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    excluded = set(value["excluded_from_first_gate"])
    assert {"Fixed10", "stress_readiness", "long_horizon_soak"}.issubset(excluded)
