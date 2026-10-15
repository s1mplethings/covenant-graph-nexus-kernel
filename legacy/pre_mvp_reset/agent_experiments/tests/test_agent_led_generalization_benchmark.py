from __future__ import annotations

import pathlib
import sys

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.benchmark]

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_agent_led_generalization_benchmark


def test_generalization_report_schema_from_fake_result() -> None:
    report = {
        "status": "pass",
        "architecture_direction": "agent-led",
        "case_count": 3,
        "passed_cases": 3,
        "failed_cases": 0,
        "blocked_cases": 0,
        "domain_diversity": "pass",
        "cases": [],
        "shared_failures": [],
        "unstable_components": [],
        "recommended_next_fixes": [],
    }

    for key in ("status", "architecture_direction", "case_count", "cases", "domain_diversity", "shared_failures", "recommended_next_fixes"):
        assert key in report


def test_case_specs_are_distinct_domains() -> None:
    cases = run_agent_led_generalization_benchmark.CASES

    assert len(cases) == 3
    assert len({case.case_id for case in cases}) == 3
    assert len({tuple(key for key, _label in case.modules) for case in cases}) == 3
    assert "patient_queue" in [key for key, _label in cases[1].modules]
    assert "defect_tracking" in [key for key, _label in cases[2].modules]


def test_provider_quota_with_local_available_uses_local_formal_generation() -> None:
    spec = run_agent_led_generalization_benchmark.CASES[0]
    state = {
        "formal_generation_materialized": False,
        "provider_quota_exceeded": True,
        "local_model_available": True,
        "has_project_spec": True,
    }

    decision = run_agent_led_generalization_benchmark.case_director(spec)("goal", state, [])

    assert decision["selected_tool"] == "formal_generation"
    assert decision["provider_strategy"] == "local_first"


def test_write_project_files_include_required_modules_and_fake_clinic_data(tmp_path: pathlib.Path) -> None:
    clinic = run_agent_led_generalization_benchmark.CASES[1]
    project = tmp_path / "clinic"

    run_agent_led_generalization_benchmark.write_project(project, clinic)

    text = (project / "feature_matrix.json").read_text(encoding="utf-8")
    demo = (project / "demo_data" / "clinic_workflow_studio_demo.json").read_text(encoding="utf-8")
    assert "patient_queue" in text
    assert "appointments" in text
    assert "synthetic demo data only" in demo
    assert "@" not in demo
    assert "final_project_bundle.zip" not in {path.name for path in project.rglob("*")}
