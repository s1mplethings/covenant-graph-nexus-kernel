from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_agent_test_integrated_behavior_contract_exists() -> None:
    text = (ROOT / "docs" / "agent_test_integrated_behavior.md").read_text(encoding="utf-8")
    assert "Requirement Decision First" in text
    assert "Strict delivery truth must not be weakened" in text
    assert "New docs, reports, tests, prompts, benchmarks, and artifacts must use CGKN" in text


def test_continuous_verified_generation_loop_contract_exists() -> None:
    text = (ROOT / "docs" / "continuous_verified_generation_loop.md").read_text(encoding="utf-8")
    for item in ["Inspect", "Decide", "Plan", "Test Contract", "Implement", "Verify", "Record Evidence", "Select Next Step"]:
        assert item in text
    assert "Requirement decision PASS must not become delivery PASS" in text
