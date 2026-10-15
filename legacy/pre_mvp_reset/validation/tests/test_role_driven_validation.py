from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "role_driven_validation", ROOT / "scripts" / "role_driven_validation.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_project_understanding_excludes_tests_and_selects_real_channels() -> None:
    understanding = module.inspect_project(ROOT / "benchmarks" / "orbit_360_workbench")

    assert understanding["project_name"] == "orbit_360_workbench"
    assert understanding["interfaces"] == ["cli", "python_api"]
    assert "tests/**" in understanding["excluded_from_understanding"]
    assert "gui" not in understanding["interfaces"]
    assert module.select_adapter(understanding) == "orbit360_v1"


def test_public_scenario_plan_never_contains_hidden_acceptance() -> None:
    understanding = module.inspect_project(ROOT / "benchmarks" / "orbit_360_workbench")
    roles = module.generate_roles(understanding, limit=4)
    scenarios = module.generate_scenarios(roles)
    public = [scenario.public_dict() for scenario in scenarios]

    assert len(public) == 4
    assert {item["role_id"] for item in public} == {
        "local_operator",
        "recovery_maintainer",
        "automation_integrator",
        "boundary_operator",
    }
    assert all("acceptance_id" not in item for item in public)
    assert all("expected" not in json.dumps(item).lower() for item in public)
    selection = module.channel_selection(understanding, scenarios)
    assert selection["selected"] == ["cli", "python_api"]
    assert selection["not_selected"] == [
        {"channel": "gui", "reason": "No public project evidence supports this channel."}
    ]


def test_independent_evaluator_detects_untruthful_clamped_delta() -> None:
    outcome = {
        "steps": [
            {
                "returncode": 0,
                "stdout": json.dumps({"delta": -1000}),
                "independent_observation": {
                    "before_weight": 63,
                    "after_weight": 1,
                    "actual_delta": -62,
                    "requested_delta": -1000,
                },
            }
        ]
    }

    evaluation = module.evaluate(outcome, "repair_extreme_truthful")

    assert evaluation["status"] == "FAIL"
    assert evaluation["production_claims_trusted"] is False
    assert evaluation["subjective_llm_judgment"]["status"] == "NOT_EVALUATED"


def test_full_ab_uses_same_version_budget_and_reproduces_role_finding(tmp_path: pathlib.Path) -> None:
    report = module.run_validation(
        ROOT / "benchmarks" / "orbit_360_workbench",
        tmp_path / "run",
        scenario_budget=4,
        action_budget=12,
    )

    assert report["comparison"]["same_project_version"] is True
    assert report["comparison"]["same_model_budget"] is True
    assert report["arms"]["baseline"]["budget"]["actions_used"] == 10
    assert report["arms"]["role_driven"]["budget"]["actions_used"] == 10
    assert report["arms"]["baseline"]["metrics"]["valid_defects"] == 0
    assert report["arms"]["role_driven"]["metrics"]["valid_defects"] == 1
    issue = report["arms"]["role_driven"]["issues"][0]
    assert issue["reproduction_status"] == "reproduced"
    assert issue["false_positive"] is False
    assert (tmp_path / "run" / "validation_report.json").is_file()
    assert (tmp_path / "run" / "role_driven" / "operations.jsonl").is_file()
