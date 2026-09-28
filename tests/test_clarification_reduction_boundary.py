from __future__ import annotations

import pathlib

from scripts import canonical_goal_spec_compiler as compiler
from scripts import requirement_decision_lane as lane


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_explicit_goal_reaches_project_plan_without_fake_blocking_question() -> None:
    spec = lane.build_goal_spec("Build a local Pomodoro timer with start, pause, reset, and work-break cycles.")
    plan = lane.build_goal_project_plan(spec)
    assert spec["status"] == "PASS" and plan["status"] == "PASS"
    assert spec["blocking_questions"] == []
    assert lane.understanding_readiness(spec)["planning_authorized"] is True


def test_conflict_is_signal_while_legacy_question_is_only_projection() -> None:
    spec = lane.build_goal_spec("The app must be offline and must be online.")
    assert spec["understanding_signals"][0]["kind"] == "contradictory_requirements"
    assert "question" not in spec["understanding_signals"][0]
    assert spec["blocking_questions"]
    assert spec["interaction_authority"] == "unassigned_pending_clarification_layer"


def test_irreversible_authorization_risk_remains_a_signal() -> None:
    spec = lane.build_goal_spec("Build a tool that permanently delete production records.")
    kinds = {item["kind"] for item in spec["understanding_signals"]}
    assert "irreversible_user_decision_required" in kinds
    assert spec["assumptions"] == []


def test_simple_goal_has_no_template_uncertainty() -> None:
    goal = "Build a local Pomodoro timer with start, pause, reset, and work-break cycles."
    spec = lane.build_goal_spec(goal)
    interpretations = lane.generate_need_interpretations(goal)
    selected = lane.select_requirement(
        lane.generate_candidate_requirements(goal, interpretations, canonical_goal_spec=spec, canonical_project_plan=lane.build_goal_project_plan(spec)),
        lane.score_candidate_requirements(
            lane.generate_candidate_requirements(goal, interpretations, canonical_goal_spec=spec, canonical_project_plan=lane.build_goal_project_plan(spec)),
            {"complex_goal": False},
        ),
    )
    rendered = lane.customer_goal_brief(goal, interpretations)
    assert selected["open_questions_not_blocking"] == []
    assert "preferred UI style" not in rendered
    assert "Exact user role" not in rendered
    assert "Runtime platform" not in rendered
    assert "external services are allowed" not in rendered


def test_assumptions_have_one_canonical_deduplicating_assembly_point() -> None:
    assert compiler.canonicalize_assumptions(["one", "one"], ["two"]) == ["one", "two"]
    interpretations = lane.generate_need_interpretations("Build a local Pomodoro timer.")
    assert all("assumptions" not in item for item in interpretations["interpreted_needs"])
    spec = lane.build_goal_spec("Build a local Pomodoro timer.")
    selected_candidates = lane.generate_candidate_requirements(
        spec["goal"], interpretations, canonical_goal_spec=spec, canonical_project_plan=lane.build_goal_project_plan(spec)
    )
    scorecard = lane.score_candidate_requirements(selected_candidates, {"complex_goal": False})
    selected = lane.select_requirement(selected_candidates, scorecard)
    assert selected["known_assumptions"] == spec["assumptions"]


def test_project_plan_consumes_only_ready_understanding() -> None:
    invalid = {"kind": "NotGoalSpec", "status": "PASS", "ready_to_generate": True}
    assert lane.understanding_readiness(invalid)["planning_authorized"] is False
    assert lane.build_goal_project_plan(invalid)["status"] == "NEEDS_REWORK"


def test_existing_requirement_decision_behavior_remains_available(tmp_path) -> None:
    result = lane.run_requirement_decision("Build a local Pomodoro timer with start, pause, reset, and work-break cycles.", tmp_path)
    assert result["status"] == "PASS"
    assert result["goal_spec"]["status"] == "PASS"
    assert result["project_plan"]["status"] == "PASS"


def test_reduced_capability_worknode_mainline_is_preserved() -> None:
    work_nodes = (ROOT / "scripts/work_nodes.py").read_text(encoding="utf-8")
    provider_jobs = (ROOT / "scripts/provider_jobs.py").read_text(encoding="utf-8")
    requirement = (ROOT / "scripts/requirement_decision_lane.py").read_text(encoding="utf-8")
    assert "class WorkNode" in work_nodes
    assert "ProviderJob" in provider_jobs
    for forbidden in ("ClarificationDecision", "UncertaintyRecord", "AssumptionLedger", "ClarificationOutcome"):
        assert forbidden not in requirement
