from __future__ import annotations

import json
import pathlib

import pytest

from scripts import goal_acceptance, post_build_finalize, post_build_repair, requirement_decision_lane, run_local_pipeline_impl


GOALS = [
    "Build a local Pomodoro timer where users can start, pause, reset and switch between work and break sessions.",
    "Build a local CSV cleaning tool that imports CSV files, detects missing values, applies cleaning rules, previews the cleaned result and exports a new CSV.",
    "Build a local visual novel story editor where users can create scenes, characters and branches, edit dialogue, preview the story flow and export the project.",
]


def _write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _goal_plan(run_dir: pathlib.Path, goal: str = GOALS[0]) -> tuple[dict, dict]:
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    _write_json(run_dir / "requirement_decision" / "goal_spec.json", spec)
    _write_json(run_dir / "requirement_decision" / "project_plan.json", plan)
    return spec, plan


def _test_source(plan: dict, *, trivial_symbol: str = "", omit_symbol: str = "") -> str:
    lines = ["from __future__ import annotations", "", "from app_logic import observe_goal", ""]
    for index, item in enumerate(plan["goal_acceptance_tests"], start=1):
        symbol = item["test_symbol"]
        if symbol == omit_symbol:
            continue
        lines.append(f"def {symbol}():")
        if symbol == trivial_symbol:
            lines.extend(
                [
                    "    observed = {'passed': True}",
                    "    assert observed['passed'] is True",
                ]
            )
        else:
            lines.extend(
                [
                    f"    observed_{index} = observe_goal({item['intent']!r})",
                    f"    assert observed_{index}['passed'] is True",
                ]
            )
        lines.append("")
    return "\n".join(lines)


def _passing_test_result() -> dict:
    return {
        "status": "pass",
        "argv": ["python", "-m", "pytest", "-q"],
        "returncode": 0,
    }


def _write_behavior_owner(project: pathlib.Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "app_logic.py").write_text(
        "def observe_goal(intent):\n"
        "    return {'intent': intent, 'passed': bool(intent)}\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("goal", GOALS, ids=["pomodoro", "csv_cleaner", "visual_novel"])
def test_goal_acceptance_passes_only_with_exact_executable_goal_tests(
    tmp_path: pathlib.Path,
    goal: str,
) -> None:
    run_dir = tmp_path / "run"
    project = tmp_path / "project"
    _, plan = _goal_plan(run_dir, goal)
    _write_behavior_owner(project)
    tests_path = project / "tests" / "test_goal_acceptance.py"
    tests_path.parent.mkdir(parents=True)
    tests_path.write_text(_test_source(plan), encoding="utf-8")

    receipt = goal_acceptance.evaluate_goal_acceptance(
        project_dir=project,
        run_dir=run_dir,
        test_result=_passing_test_result(),
    )

    assert receipt["status"] == "PASS"
    assert receipt["formal_delivery_authority"] is False
    assert receipt["required_test_symbols"] == [
        item["test_symbol"] for item in plan["goal_acceptance_tests"]
    ]
    assert all(item["accepted"] for item in receipt["mapped_tests"])


def test_goal_acceptance_rejects_missing_and_trivial_tests(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project = tmp_path / "project"
    _, plan = _goal_plan(run_dir)
    _write_behavior_owner(project)
    missing = plan["goal_acceptance_tests"][0]["test_symbol"]
    trivial = plan["goal_acceptance_tests"][1]["test_symbol"]
    tests_path = project / "tests" / "test_goal_acceptance.py"
    tests_path.parent.mkdir(parents=True)
    tests_path.write_text(
        _test_source(plan, trivial_symbol=trivial, omit_symbol=missing),
        encoding="utf-8",
    )

    receipt = goal_acceptance.evaluate_goal_acceptance(
        project_dir=project,
        run_dir=run_dir,
        test_result=_passing_test_result(),
    )

    assert receipt["status"] == "NEEDS_REWORK"
    assert f"goal_test_symbol_count:{missing}:0" in receipt["blockers"]
    assert f"goal_test_not_substantive:{trivial}" in receipt["blockers"]


def test_goal_acceptance_rejects_unexecuted_or_mismatched_evidence(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project = tmp_path / "project"
    _, plan = _goal_plan(run_dir)
    _write_behavior_owner(project)
    tests_path = project / "tests" / "test_goal_acceptance.py"
    tests_path.parent.mkdir(parents=True)
    tests_path.write_text(_test_source(plan), encoding="utf-8")
    plan["test_intents"] = ["a different behavior"]
    _write_json(run_dir / "requirement_decision" / "project_plan.json", plan)

    receipt = goal_acceptance.evaluate_goal_acceptance(
        project_dir=project,
        run_dir=run_dir,
        test_result={"status": "pass", "argv": ["python", "-m", "pytest"], "skipped": True},
    )

    assert receipt["status"] == "NEEDS_REWORK"
    assert "goal_behaviors_and_test_intents_mismatch" in receipt["blockers"]
    assert "real_test_execution_not_passed" in receipt["blockers"]


def test_goal_acceptance_rejects_non_collected_nested_test_and_non_pytest_run(
    tmp_path: pathlib.Path,
) -> None:
    run_dir = tmp_path / "run"
    project = tmp_path / "project"
    _, plan = _goal_plan(run_dir)
    _write_behavior_owner(project)
    first = plan["goal_acceptance_tests"][0]
    tests_path = project / "tests" / "test_nested.py"
    tests_path.parent.mkdir(parents=True)
    tests_path.write_text(
        "def helper():\n"
        f"    def {first['test_symbol']}():\n"
        "        observed = object()\n"
        "        assert observed is not None\n",
        encoding="utf-8",
    )

    receipt = goal_acceptance.evaluate_goal_acceptance(
        project_dir=project,
        run_dir=run_dir,
        test_result={"status": "pass", "argv": ["npm", "test"], "returncode": 0},
    )

    assert receipt["status"] == "NEEDS_REWORK"
    assert f"goal_test_symbol_count:{first['test_symbol']}:0" in receipt["blockers"]
    assert receipt["test_execution"]["pytest_executed"] is False
    assert "real_test_execution_not_passed" in receipt["blockers"]


def test_goal_acceptance_is_not_applicable_to_legacy_runs_without_goal_plan(
    tmp_path: pathlib.Path,
) -> None:
    receipt = goal_acceptance.evaluate_goal_acceptance(
        project_dir=tmp_path / "project",
        run_dir=tmp_path / "run",
        test_result=_passing_test_result(),
    )

    assert receipt["status"] == "NOT_EVALUATED"
    assert receipt["applicable"] is False
    assert receipt["formal_delivery_authority"] is False


def test_provider_test_manifest_receives_exact_goal_test_contract() -> None:
    spec = requirement_decision_lane.build_goal_spec(GOALS[1])
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    component = {"goal_acceptance_tests": plan["goal_acceptance_tests"]}
    manifest = [
        {
            "path": "tests/test_app.py",
            "purpose": "test the generated application",
            "dependencies": [],
            "expected_symbols": ["test_existing_contract"],
            "responsibilities": [],
            "acceptance_checks": [],
        }
    ]

    normalized = run_local_pipeline_impl.normalize_test_manifest_dependency_contract(
        manifest,
        ["main.py"],
        component,
    )
    entry = normalized[0]

    assert set(item["test_symbol"] for item in plan["goal_acceptance_tests"]).issubset(
        set(entry["expected_symbols"])
    )
    assert all(
        item["intent"] in " ".join(entry["responsibilities"])
        for item in plan["goal_acceptance_tests"]
    )


def test_goal_test_manifest_normalization_is_idempotent() -> None:
    spec = requirement_decision_lane.build_goal_spec(GOALS[2])
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    component = {"goal_acceptance_tests": plan["goal_acceptance_tests"]}
    manifest = [
        {
            "path": f"tests/test_part_{index}.py",
            "purpose": "goal behavior tests",
            "dependencies": [],
            "expected_symbols": [f"test_existing_{index}"],
            "responsibilities": [],
            "acceptance_checks": [],
        }
        for index in range(3)
    ]

    first = run_local_pipeline_impl.normalize_test_manifest_dependency_contract(
        manifest,
        ["main.py"],
        component,
    )
    second = run_local_pipeline_impl.normalize_test_manifest_dependency_contract(
        first,
        ["main.py"],
        component,
    )

    for item in plan["goal_acceptance_tests"]:
        symbol = item["test_symbol"]
        assert sum(symbol in entry["expected_symbols"] for entry in second) == 1
        assert sum(
            symbol in responsibility
            for entry in second
            for responsibility in entry["responsibilities"]
        ) == 1


def test_post_build_goal_acceptance_revokes_review_readiness_without_promoting_pass(
    tmp_path: pathlib.Path,
) -> None:
    run_dir = tmp_path / "run"
    project = tmp_path / "project"
    project.mkdir()
    _, plan = _goal_plan(run_dir)
    _write_behavior_owner(project)
    tests_path = project / "tests" / "test_goal_acceptance.py"
    tests_path.parent.mkdir()
    tests_path.write_text(
        _test_source(plan, omit_symbol=plan["goal_acceptance_tests"][0]["test_symbol"]),
        encoding="utf-8",
    )
    summary = project / "candidate_review_summary.json"
    _write_json(summary, {"verdict": "ASK_USER_REVIEW"})
    result = {
        "status": "pass",
        "candidate_review_ready": True,
        "candidate_review_summary": str(summary),
        "test_result": _passing_test_result(),
        "known_limits": [],
    }

    post_build_finalize.apply_goal_acceptance_gate(project, run_dir, result)

    assert result["status"] == "needs_rework"
    assert result["candidate_review_ready"] is False
    assert result["goal_acceptance"]["status"] == "NEEDS_REWORK"
    assert result["goal_acceptance"]["formal_delivery_authority"] is False
    assert not summary.exists()
    assert (run_dir / "artifacts" / "goal_acceptance.json").exists()


def test_passing_goal_acceptance_never_promotes_other_post_build_failures(
    tmp_path: pathlib.Path,
) -> None:
    run_dir = tmp_path / "run"
    project = tmp_path / "project"
    _, plan = _goal_plan(run_dir)
    _write_behavior_owner(project)
    tests_path = project / "tests" / "test_goal_acceptance.py"
    tests_path.parent.mkdir(parents=True)
    tests_path.write_text(_test_source(plan), encoding="utf-8")
    result = {
        "status": "needs_rework",
        "candidate_review_ready": False,
        "test_result": _passing_test_result(),
        "known_limits": ["visual evidence unavailable"],
    }

    post_build_finalize.apply_goal_acceptance_gate(project, run_dir, result)

    assert result["goal_acceptance"]["status"] == "PASS"
    assert result["status"] == "needs_rework"
    assert result["candidate_review_ready"] is False


def test_goal_acceptance_failure_routes_back_to_existing_test_leaf(
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "project"
    test_path = project / "tests" / "test_app.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_existing():\n    assert object() is not None\n", encoding="utf-8")
    result = {
        "goal_acceptance": {
            "applicable": True,
            "status": "NEEDS_REWORK",
            "blockers": ["goal_test_symbol_count:test_goal_01_expected:0"],
        },
        "test_result": _passing_test_result(),
        "known_limits": [],
    }

    failures = post_build_repair.classify_post_build_failures(result)
    targets = post_build_repair.default_post_build_targets(project, failures)

    assert "goal_acceptance_failure" in failures
    assert "tests/test_app.py" in targets
