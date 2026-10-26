from __future__ import annotations

import pytest

from scripts.release_057_oracle_analysis import analyze_oracle


def row(case_id: str, success: bool) -> dict[str, object]:
    return {"case_id": case_id, "domain": "test", "difficulty": "easy", "success": success}


def test_oracle_classifies_all_paired_outcomes() -> None:
    result = analyze_oracle(
        [row("a", True), row("b", True), row("c", False), row("d", False)],
        [row("a", True), row("b", False), row("c", True), row("d", False)],
    )
    assert result["classification_counts"] == {
        "ARCHITECTURE_ONLY": 1,
        "BOTH_FAIL": 1,
        "BOTH_PASS": 1,
        "DIRECT_ONLY": 1,
    }
    assert result["oracle_successes"] == 3


def test_oracle_gate_stops_when_architecture_adds_no_success() -> None:
    result = analyze_oracle(
        [row(str(index), index < 8) for index in range(10)],
        [row(str(index), index < 6) for index in range(10)],
    )
    assert result["oracle_gain_percentage_points"] == 0.0
    assert result["router_opportunity"] == "LOW_STOP_ROUTER_DEVELOPMENT"
    assert result["router_implementation_authorized"] is False


def test_oracle_gate_continues_at_five_percentage_points() -> None:
    direct = [row(str(index), index < 18) for index in range(20)]
    architecture = [row(str(index), index == 18) for index in range(20)]
    result = analyze_oracle(direct, architecture)
    assert result["oracle_gain_percentage_points"] == 5.0
    assert result["router_opportunity"] == "CONTINUE_ROUTER_V1"


def test_oracle_rejects_unpaired_inputs() -> None:
    with pytest.raises(ValueError, match="identical case IDs"):
        analyze_oracle([row("a", True)], [row("b", True)])
