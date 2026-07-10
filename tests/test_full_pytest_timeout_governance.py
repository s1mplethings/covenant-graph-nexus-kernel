from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_pytest_markers_are_registered() -> None:
    text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    for marker in ("slow", "longrun", "long_journey", "provider", "telegram", "e2e"):
        assert f"{marker}:" in text


def test_known_slow_tests_have_profile_markers() -> None:
    expected = {
        "tests/test_customer_agent_long_journey_trial.py": ("pytest.mark.longrun", "pytest.mark.long_journey", "pytest.mark.slow", "pytest.mark.e2e"),
        "tests/test_requirement_decision_pipeline_integration.py": ("pytest.mark.slow", "pytest.mark.e2e"),
        "tests/test_compose_local_pipeline.py": ("pytest.mark.slow", "pytest.mark.e2e"),
        "tests/test_reference_answer_project_trial.py": ("pytest.mark.slow", "pytest.mark.e2e"),
        "tests/test_dynamic_agent_tree_long_run_eval.py": ("pytest.mark.longrun", "pytest.mark.slow", "pytest.mark.e2e"),
        "tests/test_real_provider_large_project_delivery_eval.py": ("pytest.mark.provider", "pytest.mark.e2e"),
        "tests/test_backend_large_project_generation_eval.py": ("pytest.mark.slow", "pytest.mark.e2e"),
    }
    for rel, markers in expected.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text


def test_long_journey_has_timeout_safe_diagnostic_guard() -> None:
    text = (ROOT / "tests" / "test_customer_agent_long_journey_trial.py").read_text(encoding="utf-8")
    assert "CGKN_LONG_JOURNEY_TEST_TIMEOUT" in text
    assert "long_journey_timeout_diagnosis.json" in text
    assert "proc.terminate()" in text


def test_naked_pytest_skips_profile_marked_tests_by_default() -> None:
    text = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "DEFAULT_SKIPPED_MARKERS" in text
    assert "longrun" in text
    assert "long_journey" in text
    assert "provider" in text
    assert "telegram" in text
    assert "CGKN_INCLUDE_PROFILE_MARKS" in text
    assert "--run-profile-marked" in text
