from __future__ import annotations

import json

import pytest

from scripts import compose_local_pipeline, discovery_selection_lane, requirement_blueprint, requirement_decision_lane, run_local_pipeline_impl
from scripts.agent_tree_planner import build_agent_tree_dag
from scripts.agent_tree_shared_context import create_shared_context


CASES = [
    {
        "name": "pomodoro",
        "goal": "Build a local Pomodoro timer where users can start, pause, reset and switch between work and break sessions.",
        "domain": "productivity_timer",
        "required": ("timer", "start", "pause", "reset", "work break"),
        "stages": ("timer_domain", "timer_state", "timer_ui", "timer_behavior_tests"),
    },
    {
        "name": "csv_cleaner",
        "goal": "Build a local CSV cleaning tool that imports CSV files, detects missing values, applies cleaning rules, previews the cleaned result and exports a new CSV.",
        "domain": "csv_cleaning_tool",
        "required": ("csv", "import", "missing values", "cleaning", "preview", "export"),
        "stages": ("csv_import", "cleaning_engine", "result_preview", "csv_export", "cleaning_tests"),
    },
    {
        "name": "visual_novel",
        "goal": "Build a local visual novel story editor where users can create scenes, characters and branches, edit dialogue, preview the story flow and export the project.",
        "domain": "visual_novel_editor",
        "required": ("scene", "character", "branch", "dialogue", "preview", "export"),
        "stages": ("story_model", "scene_editor", "character_editor", "branch_editor", "preview_export", "story_behavior_tests"),
    },
]

KNOWLEDGE_ONLY_TERMS = (
    "knowledge studio",
    "document import",
    "knowledge base",
    "document service",
    "search service",
    "report service",
    "model adapter",
)


def normalized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).lower().replace("_", " ").replace("/", " ")


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_goal_spec_and_project_plan_follow_product_goal(case: dict[str, object]) -> None:
    goal = str(case["goal"])
    goal_spec = requirement_decision_lane.build_goal_spec(goal)
    project_plan = requirement_decision_lane.build_goal_project_plan(goal_spec)
    shared_context = create_shared_context(str(case["name"]), goal)
    dag = build_agent_tree_dag(shared_context)
    combined = normalized({"goal_spec": goal_spec, "project_plan": project_plan, "dag": dag})

    assert goal_spec["status"] == "PASS"
    assert goal_spec["domain"] == case["domain"]
    assert project_plan["status"] == "PASS"
    assert goal_spec["capabilities"]
    assert goal_spec["user_flows"]
    assert goal_spec["entities"]
    assert goal_spec["interfaces"]
    assert goal_spec["acceptance_behaviors"] == project_plan["test_intents"]
    assert [item["intent"] for item in project_plan["goal_acceptance_tests"]] == project_plan["test_intents"]
    assert len({item["test_symbol"] for item in project_plan["goal_acceptance_tests"]}) == len(project_plan["test_intents"])
    for term in case["required"]:
        assert str(term) in combined
    stage_ids = {str(row["id"]) for row in project_plan["workstreams"]}
    assert set(case["stages"]).issubset(stage_ids)
    assert {str(row["workstream_id"]) for row in project_plan["leaves"]} == stage_ids
    assert project_plan["business_outputs"]
    for forbidden in KNOWLEDGE_ONLY_TERMS:
        assert forbidden not in combined


def test_cross_goal_business_scope_is_structurally_distinct() -> None:
    projections: dict[str, dict[str, object]] = {}
    for case in CASES:
        spec = requirement_decision_lane.build_goal_spec(str(case["goal"]))
        plan = requirement_decision_lane.build_goal_project_plan(spec)
        projections[str(case["name"])] = {
            "capabilities": spec["capabilities"],
            "user_flows": spec["user_flows"],
            "entities": spec["entities"],
            "leaf_scopes": [row["scope"] for row in plan["leaves"]],
            "test_intents": plan["test_intents"],
            "business_outputs": plan["business_outputs"],
        }

    values = [normalized(value) for value in projections.values()]
    assert len(values) == len(set(values)) == 3
    for left_index, left in enumerate(values):
        for right in values[left_index + 1 :]:
            assert left != right


def test_production_component_route_consumes_canonical_goal_plan() -> None:
    for case in CASES:
        goal = str(case["goal"])
        spec = requirement_decision_lane.build_goal_spec(goal)
        plan = requirement_decision_lane.build_goal_project_plan(spec)
        plan_doc = {
            "pipeline_plan": {"payload": {"component_pipeline": compose_local_pipeline.build_component_pipeline(goal)}},
            "goal_spec": spec,
            "project_plan": plan,
        }

        component_pipeline = run_local_pipeline_impl.component_pipeline_from_plan(goal, plan_doc)

        assert component_pipeline["canonical_goal_spec"] == spec
        assert component_pipeline["canonical_project_plan"] == plan
        assigned = {
            str(row["id"])
            for component in component_pipeline["components"]
            for row in component.get("business_workstreams", [])
        }
        expected = {str(row["id"]) for row in plan["workstreams"]}
        assert expected.issubset(assigned)
        tests_component = next(row for row in component_pipeline["components"] if row["id"] == "tests")
        assert tests_component["test_intents"] == spec["acceptance_behaviors"]
        assert tests_component["goal_acceptance_tests"] == plan["goal_acceptance_tests"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_production_discovery_consumes_same_goal_plan(case: dict[str, object], tmp_path) -> None:
    goal = str(case["goal"])
    requirement = requirement_decision_lane.run_requirement_decision(goal, tmp_path / "requirements")
    spec = requirement["goal_spec"]
    plan = requirement["project_plan"]

    discovery = discovery_selection_lane.run_discovery_selection(
        goal,
        tmp_path / "discovery",
        goal_spec=spec,
        project_plan=plan,
    )
    selected = discovery["selected_project_direction"]
    alignment = run_local_pipeline_impl.requirement_discovery_alignment(
        requirement["selected_requirement"],
        selected,
    )

    assert discovery["status"] == "PASS"
    assert selected["goal_spec_domain"] == case["domain"]
    assert selected["canonical_goal_spec"] == spec
    assert selected["canonical_project_plan"] == plan
    assert alignment["status"] == "PASS"
    assert alignment["requirement_domain"] == alignment["direction_domain"] == case["domain"]
    for forbidden in KNOWLEDGE_ONLY_TERMS:
        assert forbidden not in normalized({"selected": selected, "contract": discovery["complexity_project_contract"]})


def test_requirement_blueprint_projects_canonical_goal_truth() -> None:
    case = CASES[1]
    goal = str(case["goal"])
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)

    blueprint = requirement_blueprint.build_requirement_blueprint(
        goal,
        [],
        assume_defaults=False,
        goal_spec=spec,
        project_plan=plan,
    )

    assert blueprint["canonical_goal_spec"] == spec
    assert blueprint["canonical_project_plan"] == plan
    assert blueprint["requirement_spec"]["required_features"]["value"] == spec["capabilities"]
    assert {row["id"] for row in blueprint["frontend_pages"]["pages"]} == set(spec["interfaces"])


def test_unknown_explicit_goal_never_falls_back_to_knowledge_studio(tmp_path) -> None:
    goal = "Build a local choreography notation editor for planning dance sequences."
    result = requirement_decision_lane.run_requirement_decision(goal, tmp_path)
    combined = normalized(result)

    assert result["status"] == "PASS"
    assert result["goal_spec"]["domain"] == "choreography_notation_editor"
    assert "movement" in combined
    assert "sequence" in combined
    for forbidden in KNOWLEDGE_ONLY_TERMS:
        assert forbidden not in combined


def test_insufficient_goal_returns_needs_rework_without_template_fallback(tmp_path) -> None:
    result = requirement_decision_lane.run_requirement_decision("Build something local.", tmp_path)

    assert result["status"] == "NEEDS_REWORK"
    assert result["goal_spec"]["reason"] == "INSUFFICIENT_GOAL_PLAN"
    assert result["project_plan"]["workstreams"] == []
    assert "knowledge" not in normalized({"goal_spec": result["goal_spec"], "project_plan": result["project_plan"]})


def test_explicit_knowledge_studio_goal_retains_knowledge_capabilities() -> None:
    goal = "Build a local AI Knowledge Studio with document import, knowledge search, reports, tasks and a local model adapter."
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    combined = normalized({"goal_spec": spec, "project_plan": plan})

    assert spec["domain"] == "local_ai_knowledge_studio"
    for term in ("document", "knowledge", "search", "task", "report", "model adapter"):
        assert term in combined
    assert {row["id"] for row in plan["workstreams"]} >= {
        "document_import", "knowledge_search", "task_reporting", "model_adapter"
    }
