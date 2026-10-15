from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import agent_tool_registry


def test_tool_registry_contains_agent_director_tools() -> None:
    names = set(agent_tool_registry.tool_names())

    assert {
        "formal_generation",
        "semantic_review",
        "candidate_repair",
        "final_promotion",
        "artifact_integrity_check",
        "public_delivery_gate",
        "product_acceptance",
        "commercial_readiness",
    }.issubset(names)


def test_formal_live_delivery_closure_is_tool_not_controller() -> None:
    tool = agent_tool_registry.get_tool("formal_live_delivery_closure")

    assert tool is not None
    assert tool["risk_level"] == "high"
    assert "outputs" in tool
    assert "formal_live_delivery_closure_report" in tool["outputs"]


def test_tool_registry_contains_autonomous_diagnosis_tools() -> None:
    names = set(agent_tool_registry.tool_names())

    assert {
        "inspect_latest_reports",
        "inspect_decision_ledger",
        "inspect_model_ledger",
        "run_agent_led_verify",
        "run_large_project_benchmark",
        "run_targeted_tests",
        "repair_verify_entry",
        "repair_provider_fallback",
        "repair_candidate",
        "repair_final_promotion",
        "repair_delivery_evidence",
        "repair_product_acceptance",
        "repair_complexity_generation",
        "stability_rerun",
    }.issubset(names)
