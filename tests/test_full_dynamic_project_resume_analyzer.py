from __future__ import annotations

import pathlib

import pytest

from scripts.full_dynamic_project_resume_analyzer import analyze_previous_run


ROOT = pathlib.Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / "generated" / "full_dynamic_real_project_eval"
pytestmark = pytest.mark.e2e


def test_analyzer_recovers_previous_leaf_states_and_cache(tmp_path: pathlib.Path) -> None:
    analysis, plan, cache = analyze_previous_run(PREVIOUS, out_dir=tmp_path)

    assert analysis["summary"] == {
        "total_leaf": 14,
        "pass_leaf": 9,
        "provider_unavailable_leaf": 4,
        "test_failed_leaf": 1,
        "scope_violation_leaf": 0,
        "missing_files_leaf": 0,
    }
    assert set(plan["resume_leaf"]) == {"dashboard_page_leaf", "settings_page_leaf", "smoke_test_leaf", "tasks_page_leaf"}
    assert plan["repair_leaf"] == ["search_service_leaf"]
    assert cache["reused_count"] == 9
    assert cache["hash_verified"] is True
    assert all(item["provider_called_during_resume"] is False for item in cache["reused_leaves"])


def test_analyzer_records_downstream_was_not_executed(tmp_path: pathlib.Path) -> None:
    analysis, plan, _ = analyze_previous_run(PREVIOUS, out_dir=tmp_path)

    assert analysis["integration"] == "SKIPPED"
    assert analysis["public_delivery_gate"] == "NOT_RUN"
    assert "runtime_visual_evidence" in plan["blocked_downstream"]
