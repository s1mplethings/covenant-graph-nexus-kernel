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

EXAM_LEARNING_GOAL = (
    "Build a durable local-first Chinese web application named YanTu Computer for mainland China "
    "postgraduate computer-science exam preparation. Use a Python 3.11 backend, SQLite persistence, "
    "and a responsive browser UI without requiring a cloud account. Core workflows: create an "
    "adjustable study plan from exam date, weekly available time, and topic weakness; manage a "
    "hierarchical knowledge map and Markdown notes; create or import user-owned questions; practice "
    "and record answers, explanations, mastery, and elapsed time; maintain a wrong-answer notebook; "
    "schedule due reviews with a transparent forgetting-review algorithm; track daily study sessions "
    "and Pomodoro time; show completion, accuracy, streak, and weak-topic dashboards; global "
    "search/filter; JSON backup, restore, and export. The user interface and README must be Chinese, "
    "keyboard accessible, and mobile friendly."
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


def test_secondary_fixed_profile_feature_cannot_replace_broad_primary_product() -> None:
    goal_spec = requirement_decision_lane.build_goal_spec(EXAM_LEARNING_GOAL)
    project_plan = requirement_decision_lane.build_goal_project_plan(goal_spec)
    combined = normalized({"goal_spec": goal_spec, "project_plan": project_plan})

    assert goal_spec["status"] == "PASS"
    assert goal_spec["domain"] == "custom_local_application"
    assert len(goal_spec["user_flows"]) >= 9
    assert "DomainRecord" not in goal_spec["entities"]
    assert "ProjectState" not in goal_spec["entities"]
    assert "StudyPlan" in goal_spec["entities"]
    assert goal_spec["entrypoints"] == ["app.main"]
    assert len(project_plan["goal_acceptance_tests"]) == len(goal_spec["user_flows"])
    workstreams_by_id = {row["id"]: row for row in project_plan["workstreams"]}
    assert {"domain_models", "persistence_repository", "application_service"} <= set(
        workstreams_by_id
    )
    assert workstreams_by_id["persistence_repository"]["depends_on"] == [
        "foundation",
        "domain_models",
    ]
    assert workstreams_by_id["application_service"]["depends_on"] == [
        "domain_models",
        "persistence_repository",
    ]
    assert workstreams_by_id["application_entry"]["depends_on"] == [
        "foundation",
        "application_service",
    ]
    for required in (
        "study plan",
        "knowledge map",
        "user owned questions",
        "wrong answer notebook",
        "due reviews",
        "pomodoro",
        "dashboards",
        "search filter",
        "backup restore",
    ):
        assert required in combined
    assert "timer domain" not in {row["id"].replace("_", " ") for row in project_plan["workstreams"]}


def test_goal_plan_paths_replace_inherited_duplicate_backend_architecture() -> None:
    goal_spec = requirement_decision_lane.build_goal_spec(EXAM_LEARNING_GOAL)
    project_plan = requirement_decision_lane.build_goal_project_plan(goal_spec)
    base_pipeline = compose_local_pipeline.build_component_pipeline(EXAM_LEARNING_GOAL)
    for component in base_pipeline["components"]:
        if component["id"] == "backend":
            component["required_paths"] = [
                "main.py",
                "backend/stages.py",
                "backend/orchestrator.py",
                "backend/artifact_store.py",
            ]
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        EXAM_LEARNING_GOAL,
        {
            "pipeline_plan": {"payload": {"component_pipeline": base_pipeline}},
            "goal_spec": goal_spec,
            "project_plan": project_plan,
        },
    )
    backend = next(row for row in pipeline["components"] if row["id"] == "backend")
    expected_backend_outputs = [
        str(path)
        for workstream in backend["business_workstreams"]
        for path in workstream.get("expected_outputs", [])
    ]

    assert backend["required_path_authority"] == "canonical_goal_project_plan"
    assert backend["required_paths"] == list(dict.fromkeys(expected_backend_outputs))
    assert backend["required_paths"]
    assert all(
        path == "app/main.py" or path.startswith("src/")
        for path in backend["required_paths"]
    )
    assert "app/main.py" in backend["required_paths"]
    assert "src/domain_models.py" in backend["required_paths"]
    assert "src/repository.py" in backend["required_paths"]
    assert "src/service.py" in backend["required_paths"]
    assert "main.py" not in backend["required_paths"]
    assert "backend/stages.py" not in backend["required_paths"]
    assert "backend/artifact_store.py" not in backend["required_paths"]


def test_visual_goal_plan_assigns_owned_web_files_only_to_frontend() -> None:
    goal = str(next(case["goal"] for case in CASES if case["name"] == "visual_novel"))
    goal_spec = requirement_decision_lane.build_goal_spec(goal)
    project_plan = requirement_decision_lane.build_goal_project_plan(goal_spec)
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        goal,
        {
            "pipeline_plan": {
                "payload": {
                    "component_pipeline": compose_local_pipeline.build_component_pipeline(goal)
                }
            },
            "goal_spec": goal_spec,
            "project_plan": project_plan,
        },
    )
    components = {row["id"]: row for row in pipeline["components"]}
    expected_frontend_paths = {
        "frontend/index.html",
        "frontend/styles.css",
        "frontend/app.js",
    }

    assert expected_frontend_paths.issubset(components["frontend"]["required_paths"])
    assert expected_frontend_paths.isdisjoint(components["backend"]["required_paths"])
    assert any(
        row["id"] == "user_interface"
        for row in components["frontend"]["business_workstreams"]
    )
    assert all(
        row["id"] != "user_interface"
        for row in components["backend"]["business_workstreams"]
    )


def test_goal_plan_workstream_relationships_become_leaf_dependencies_and_symbols() -> None:
    goal_spec = requirement_decision_lane.build_goal_spec(EXAM_LEARNING_GOAL)
    project_plan = requirement_decision_lane.build_goal_project_plan(goal_spec)
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        EXAM_LEARNING_GOAL,
        {
            "pipeline_plan": {
                "payload": {
                    "component_pipeline": compose_local_pipeline.build_component_pipeline(
                        EXAM_LEARNING_GOAL
                    )
                }
            },
            "goal_spec": goal_spec,
            "project_plan": project_plan,
        },
    )
    backend = next(row for row in pipeline["components"] if row["id"] == "backend")
    manifest = [
        {
            "path": path,
            "dependencies": ["backend/invented.py"],
            "expected_symbols": [],
        }
        for path in backend["required_paths"]
    ]
    normalized = run_local_pipeline_impl.normalize_goal_plan_manifest_dependency_contract(
        manifest, backend
    )
    by_path = {entry["path"]: entry for entry in normalized}
    first_workflow = next(
        row
        for row in backend["business_workstreams"]
        if row["id"]
        not in {
            "application_entry",
            "domain_models",
            "persistence_repository",
            "application_service",
        }
    )
    first_workflow_path = first_workflow["expected_outputs"][0]

    assert by_path["src/domain_models.py"]["dependencies"] == []
    assert by_path["src/repository.py"]["dependencies"] == [
        "src/domain_models.py"
    ]
    assert by_path["src/service.py"]["dependencies"] == [
        "src/domain_models.py",
        "src/repository.py",
    ]
    assert by_path[first_workflow_path]["dependencies"] == ["src/service.py"]
    assert by_path[first_workflow_path]["expected_symbols"] == [
        first_workflow["id"]
    ]
    assert by_path["app/main.py"]["dependencies"] == ["src/service.py"]
    assert by_path["app/main.py"]["expected_symbols"] == ["main"]


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


FEATURE_UNIT_GOAL = (
    "Create a minimal Python 3.11 command-line project named qwen_leaf_probe using only the standard library. "
    "Implement an importable normalize_title(value: str) -> str function that strips surrounding whitespace "
    "and raises ValueError when the result is blank. The CLI accepts exactly one title argument and prints "
    "exactly one JSON object with the normalized title. Include pyproject.toml, requirements.txt, README.md, "
    "TEST_PLAN.md, package source, and focused pytest tests for normalization, blank rejection, and CLI JSON "
    "output. Do not add persistence, networking, frameworks, or unrelated features. Keep the implementation "
    "small and runnable."
)


def test_explicit_single_operation_becomes_one_minimal_feature_contract(tmp_path) -> None:
    spec = requirement_decision_lane.build_goal_spec(FEATURE_UNIT_GOAL)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    feature = spec["feature_contracts"][0]

    assert spec["status"] == "PASS"
    assert spec["domain"] == "feature_unit_application"
    assert spec["package_name"] == "qwen_leaf_probe"
    assert spec["capabilities"] == ["normalize_title"]
    assert feature["public_entrypoint"] == {
        "name": "normalize_title",
        "signature": "normalize_title(value: str) -> str",
        "inputs": [{"name": "value", "type": "str", "required": True}],
        "output": {"type": "str"},
    }
    assert feature["errors"] == [
        {"type": "ValueError", "condition": "normalized input is blank"}
    ]
    assert feature["side_effects"] == []
    assert feature["dependencies"] == []
    assert len(feature["interface_sha256"]) == 64
    assert spec["feature_interface_freeze"]["frozen"] is True
    assert spec["feature_interface_freeze"]["conflicts"] == []
    assert {
        "no_persistence",
        "no_network",
        "no_frameworks",
        "no_unrelated_features",
    } <= set(spec["constraints"])
    assert plan["expected_project_structure"] == [
        "pyproject.toml",
        "requirements.txt",
        "qwen_leaf_probe/normalize_title.py",
        "qwen_leaf_probe/__init__.py",
        "qwen_leaf_probe/__main__.py",
        "tests/test_normalize_title.py",
        "README.md",
        "TEST_PLAN.md",
        "DELIVERY_NOTES.md",
    ]
    test_workstream = next(
        row for row in plan["workstreams"] if row["id"] == "feature_normalize_title_tests"
    )
    assert test_workstream["expected_symbols"] == [
        row["test_symbol"] for row in plan["goal_acceptance_tests"]
    ]
    combined = normalized({"spec": spec, "plan": plan})
    for forbidden in (
        "domain record",
        "project state",
        "repository",
        "application service",
        "persistence repository",
        "plan domain workflow",
        "import domain data",
        "orchestrator",
        "stages.py",
    ):
        assert forbidden not in combined

    discovery = discovery_selection_lane.run_discovery_selection(
        FEATURE_UNIT_GOAL,
        tmp_path / "discovery",
        goal_spec=spec,
        project_plan=plan,
    )
    contract = discovery["complexity_project_contract"]
    assert contract["architecture_mode"] == "feature_unit_application"
    assert contract["required_planning_docs"] == []
    assert contract["required_pipeline_stages"] == []
    assert contract["required_stage_artifacts"] == []
    assert "single_file_demo" not in contract["forbidden_shortcuts"]


def test_frozen_independent_features_share_one_parallel_batch_and_isolate_repair() -> None:
    goal = (
        "Create a minimal Python project named multi_probe. Implement clean(value: str) -> str function "
        "and count_words(value: str) -> int function. Use only the standard library and do not add "
        "persistence, networking, frameworks, or unrelated features."
    )
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        goal,
        {
            "pipeline_plan": {
                "payload": {
                    "component_pipeline": compose_local_pipeline.build_component_pipeline(goal)
                }
            },
            "goal_spec": spec,
            "project_plan": plan,
        },
    )
    backend = next(row for row in pipeline["components"] if row["id"] == "backend")
    tests_component = next(row for row in pipeline["components"] if row["id"] == "tests")
    manifest = run_local_pipeline_impl.compiled_feature_unit_component_manifest(
        "backend", backend
    )
    graph = run_local_pipeline_impl.build_component_leaf_work_graph("backend", manifest)
    batches = [
        [leaf["path"] for leaf in batch]
        for batch in run_local_pipeline_impl.component_leaf_ready_batches(graph)
    ]

    assert spec["capabilities"] == ["clean", "count_words"]
    assert plan["feature_parallel_batches"] == [["clean", "count_words"]]
    assert batches[0] == ["multi_probe/clean.py", "multi_probe/count_words.py"]
    assert batches[1] == ["multi_probe/__init__.py"]
    assert run_local_pipeline_impl.component_leaf_downstream_closure(
        graph, ["multi_probe/clean.py"]
    ) == ["multi_probe/clean.py", "multi_probe/__init__.py"]
    assert "multi_probe/count_words.py" not in run_local_pipeline_impl.component_leaf_downstream_closure(
        graph, ["multi_probe/clean.py"]
    )
    owned = [
        path
        for feature in spec["feature_contracts"]
        for path in feature["owned_paths"]
    ]
    assert len(owned) == len(set(owned))


def test_typed_feature_signatures_stop_before_business_prose() -> None:
    goal = (
        "Build a Python project named kaoyan_companion. Place the functions at "
        "kaoyan_companion/allocate_subject_hours.py, kaoyan_companion/rank_review_topics.py, "
        "and kaoyan_companion/build_revision_calendar.py. "
        "allocate_subject_hours(subject_weights_json: str, weekly_hours: float) -> str parses "
        "positive weights and returns 2-decimal hours. "
        "rank_review_topics(topics_json: str) -> str validates mastery 0..100 and sorts topics. "
        "build_revision_calendar(start_date: str, exam_date: str, daily_hours: float) -> str "
        "validates ISO dates. Use only the standard library."
    )

    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)

    assert [
        feature["public_entrypoint"]["signature"]
        for feature in spec["feature_contracts"]
    ] == [
        "allocate_subject_hours(subject_weights_json: str, weekly_hours: float) -> str",
        "rank_review_topics(topics_json: str) -> str",
        "build_revision_calendar(start_date: str, exam_date: str, daily_hours: float) -> str",
    ]
    assert {
        "kaoyan_companion/allocate_subject_hours.py",
        "kaoyan_companion/rank_review_topics.py",
        "kaoyan_companion/build_revision_calendar.py",
    } <= set(plan["expected_project_structure"])


def test_feature_unit_manifest_is_compiled_without_provider_planning_turn(monkeypatch, tmp_path) -> None:
    spec = requirement_decision_lane.build_goal_spec(FEATURE_UNIT_GOAL)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        FEATURE_UNIT_GOAL,
        {
            "pipeline_plan": {
                "payload": {
                    "component_pipeline": compose_local_pipeline.build_component_pipeline(
                        FEATURE_UNIT_GOAL
                    )
                }
            },
            "goal_spec": spec,
            "project_plan": plan,
        },
    )
    backend = next(row for row in pipeline["components"] if row["id"] == "backend")
    tests_component = next(
        row for row in pipeline["components"] if row["id"] == "tests"
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_text",
        lambda *_args, **_kwargs: pytest.fail("feature manifest must not call Provider"),
    )

    manifest = run_local_pipeline_impl.provider_component_file_manifest(
        goal=FEATURE_UNIT_GOAL,
        component=backend,
        component_pipeline=pipeline,
        prior_manifest=["pyproject.toml", "requirements.txt"],
        repair_errors=[],
        model="qwen3.8-max",
        timeout=30,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        routing_policy=None,
    )

    assert [entry["path"] for entry in manifest] == [
        "qwen_leaf_probe/normalize_title.py",
        "qwen_leaf_probe/__init__.py",
        "qwen_leaf_probe/__main__.py",
    ]
    assert manifest[0]["feature_contracts"][0]["feature_id"] == "normalize_title"
    assert manifest[0]["maximum_nonblank_lines"] == 80
    tests_manifest = run_local_pipeline_impl.compiled_feature_unit_component_manifest(
        "tests", tests_component
    )
    assert tests_manifest[0]["dependencies"] == [
        "qwen_leaf_probe/normalize_title.py",
        "qwen_leaf_probe/__init__.py",
        "qwen_leaf_probe/__main__.py",
    ]
    assert tests_manifest[0]["expected_symbols"] == [
        row["test_symbol"] for row in plan["goal_acceptance_tests"]
    ]
    assert any(
        '"-m", "qwen_leaf_probe"' in item
        for item in tests_manifest[0]["acceptance_checks"]
    )
    events = [
        json.loads(line)
        for line in (tmp_path / "provider_phase_log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "component_file_manifest_compiled"
    assert events[-1]["provider_source_authorship_unchanged"] is True


def test_feature_unit_test_manifest_freezes_supervised_stdin_and_quality_rules() -> None:
    goal = (
        "Create a minimal Python CLI project named stdin_probe. Implement "
        "normalize_title(value: str) -> str function. The CLI reads one JSON request only "
        "from stdin. Tests use subprocess through stdin, never argv, and cover determinism "
        "and all relevant error classes. Raise ValueError('declared invalid input') for invalid input."
    )
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        goal,
        {
            "pipeline_plan": {
                "payload": {
                    "component_pipeline": compose_local_pipeline.build_component_pipeline(goal)
                }
            },
            "goal_spec": spec,
            "project_plan": plan,
        },
    )
    tests_component = next(
        row for row in pipeline["components"] if row["id"] == "tests"
    )
    tests_component["codex_capability_supervision"] = {
        "acceptance_checks": [
            "Every declared invalid input raises ValueError('declared invalid input').",
            "The CLI reads exactly one request only from stdin.",
            "Each focused test module covers determinism and all relevant error classes.",
        ],
        "provider_guidance": [
            "Tests use subprocess through stdin rather than argv.",
            "CLI success contains result as json.loads(function_return).",
        ],
    }

    manifest = run_local_pipeline_impl.compiled_feature_unit_component_manifest(
        "tests", tests_component
    )
    entry = manifest[0]
    graph = run_local_pipeline_impl.build_component_leaf_work_graph("tests", manifest)

    assert entry["feature_test_contract"] == {
        "stdin_json_cli": True,
        "cli_result_parsed_json": True,
        "determinism_required": True,
        "declared_error_coverage_required": True,
        "exact_error_messages": ["declared invalid input"],
    }
    combined_acceptance = " ".join(entry["acceptance_checks"])
    assert "test_*determin*" in combined_acceptance
    assert "nested payload" in combined_acceptance
    assert "never append operation or payload argv" in combined_acceptance
    assert ", title]" not in combined_acceptance
    assert graph["leaves"][0]["feature_test_contract"] == entry["feature_test_contract"]


def test_explicit_custom_cli_derives_commands_entity_constraints_and_acceptance(tmp_path) -> None:
    goal = (
        "Build a compact offline Python Notes CLI. Commands: add, list, search, and delete. "
        "Persist versioned JSON atomically, emit stable JSON output, search case-insensitively, "
        "and fail safely on corrupt storage without a network service."
    )

    result = requirement_decision_lane.run_requirement_decision(goal, tmp_path)
    spec = result["goal_spec"]
    plan = result["project_plan"]
    combined = normalized({"spec": spec, "plan": plan})

    assert result["status"] == "PASS"
    assert spec["domain"] == "local_record_cli"
    assert spec["entities"] == ["Note", "NoteRepository", "NoteService"]
    assert spec["interaction_modes"] == ["cli"]
    assert {"add_note", "list_note", "search_note", "delete_note"} <= set(spec["capabilities"])
    for term in ("atomic", "versioned json", "case insensitive", "corrupt storage", "not-found"):
        assert term in combined
    assert {row["id"] for row in plan["workstreams"]} >= {
        "record_model_repository", "record_service_cli", "record_behavior_tests"
    }
    assert "backend/record_model_repository.py" in plan["expected_project_structure"]
    assert "backend/record_service_cli.py" in plan["expected_project_structure"]
    assert not any(path.startswith("src/record_") for path in plan["expected_project_structure"])
    discovery = discovery_selection_lane.run_discovery_selection(
        goal,
        tmp_path / "discovery",
        goal_spec=spec,
        project_plan=plan,
    )
    contract = discovery["complexity_project_contract"]
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        goal,
        {
            "pipeline_plan": {"payload": {"component_pipeline": compose_local_pipeline.build_component_pipeline(goal)}},
            "goal_spec": spec,
            "project_plan": plan,
            "selected_project_direction": discovery["selected_project_direction"],
            "complexity_project_contract": contract,
        },
    )
    backend = next(row for row in pipeline["components"] if row["id"] == "backend")

    assert contract["architecture_mode"] == "direct_cli_application"
    assert contract["required_planning_docs"] == []
    assert contract["required_pipeline_stages"] == []
    assert contract["required_stage_artifacts"] == []


    assert "backend/stages.py" not in backend["required_paths"]
    assert "backend/orchestrator.py" not in backend["required_paths"]
    assert "backend/artifact_store.py" not in backend["required_paths"]
    assert "backend/adapters.py" not in backend["required_paths"]
    assert "backend/main.py" not in backend["required_paths"]
    assert "main.py" in backend["required_paths"]

    normalized_manifest = run_local_pipeline_impl.normalize_direct_cli_manifest_contract(
        "backend",
        [
            {"path": "backend/cli.py", "dependencies": [], "expected_symbols": ["NoteCLI"]},
            {"path": "main.py", "dependencies": [], "expected_symbols": ["app"]},
            {"path": "backend/main.py", "dependencies": [], "expected_symbols": ["RecordServiceCLI"]},
            {"path": "backend/record_service_cli.py", "dependencies": [], "expected_symbols": ["NoteServiceCLI"]},
            {"path": "backend/record_model_repository.py", "dependencies": [], "expected_symbols": ["NoteRepository"]},
        ],
        backend,
    )
    by_path = {row["path"]: row for row in normalized_manifest}

    assert "backend/main.py" not in by_path
    assert by_path["backend/record_service_cli.py"]["dependencies"] == ["backend/record_model_repository.py"]
    assert by_path["backend/cli.py"]["dependencies"] == [
        "backend/record_model_repository.py",
        "backend/record_service_cli.py",
    ]
    assert by_path["main.py"]["dependencies"] == ["backend/cli.py"]
    assert by_path["backend/record_model_repository.py"]["expected_symbols"] == ["Note", "NoteRepository"]
    assert by_path["backend/record_service_cli.py"]["expected_symbols"] == ["NoteService"]
    assert by_path["backend/cli.py"]["expected_symbols"] == ["build_parser", "run_cli"]
    assert by_path["main.py"]["expected_symbols"] == ["main"]

    backend["codex_capability_supervision"] = {
        "kind": "CGKNCodexCapabilityProviderGuidance",
        "provider_guidance": ["Keep repository and service return values separate from CLI JSON output."],
    }
    split_context = run_local_pipeline_impl.summarize_component_context_for_split(
        goal=goal,
        component=backend,
        component_pipeline=pipeline,
        prior_manifest=[],
        repair_errors=[],
        librarian_context_pack={
            "query_kind": "leaf_generation",
            "index_sha256": "a" * 64,
            "query_sha256": "b" * 64,
            "selected_items": [{"path": "backend/record_model_repository.py", "content": "x" * 20000}],
        },
    )
    assert split_context["codex_capability_supervision"]["provider_guidance"]
    assert split_context["librarian_context"]["selected_paths"] == ["backend/record_model_repository.py"]
    assert "selected_items" not in split_context["librarian_context"]
    service_contract = run_local_pipeline_impl.direct_cli_leaf_contract(
        backend, "backend/record_service_cli.py"
    )
    assert service_contract["required_symbols"] == ["NoteService"]
    assert any("never print" in rule for rule in service_contract["api"])
    test_contract = run_local_pipeline_impl.direct_cli_leaf_contract(
        backend, "tests/test_record_behavior_tests.py"
    )
    assert any("no invented get/update" in rule for rule in test_contract["test_contract"])
    prompt = '{"direct_cli_leaf_contract":{}}'
    repository_error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "backend/record_model_repository.py",
            "content": (
                "from dataclasses import dataclass\nimport json\nimport os\n"
                "time = None\nclock = time.time\n"
                "@dataclass\nclass Note:\n    id: int\n    title: str\n    body: str\n"
                "class NoteRepository:\n    pass\n"
            ),
        },
        stage="component_file_generation",
        component="backend",
        target_file="backend/record_model_repository.py",
        prompt_text=prompt,
    )
    assert "next integer ID" in repository_error
    service_error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "backend/record_service_cli.py",
            "content": "from __future__ import annotations\nimport argparse\nclass NoteService:\n    pass\ndef run_cli():\n    return 0\n",
        },
        stage="component_file_generation",
        component="backend",
        target_file="backend/record_service_cli.py",
        prompt_text=prompt,
    )
    assert "no ID/storage/argparse/run_cli ownership" in service_error
    cli_error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "backend/cli.py",
            "content": "from backend.record_service_cli import run_cli\ndef build_parser():\n    return None\n",
        },
        stage="component_file_generation",
        component="backend",
        target_file="backend/cli.py",
        prompt_text=prompt,
    )
    assert "must define, not import" in cli_error

    tests_component = next(row for row in pipeline["components"] if row["id"] == "tests")
    normalized_tests = run_local_pipeline_impl.normalize_test_manifest_dependency_contract(
        [
            {"path": "tests/test_app.py", "expected_symbols": ["test_large_dataset"], "dependencies": []},
            {"path": "tests/test_record_behavior_tests.py", "expected_symbols": ["test_concurrent_operations"], "dependencies": []},
        ],
        ["backend/record_model_repository.py", "backend/record_service_cli.py", "backend/cli.py", "main.py"],
        tests_component,
    )
    normalized_symbols = {
        symbol for row in normalized_tests for symbol in row["expected_symbols"]
    }
    canonical_symbols = {
        row["test_symbol"] for row in plan["goal_acceptance_tests"]
    }

    assert normalized_symbols == canonical_symbols
    assert all(len(symbol) <= 64 for symbol in canonical_symbols)
    assert "test_large_dataset" not in normalized_symbols
    assert "test_concurrent_operations" not in normalized_symbols


def test_projectpulse_cli_expands_every_explicit_acceptance_behavior(tmp_path) -> None:
    goal = (
        "Generate a Python 3.11 CLI project named ProjectPulse. It must support add, "
        "list with status filtering, complete, delete, summary, JSON export, and JSON "
        "import with merge and replace modes; persist data atomically in a user-selectable "
        "JSON file; expose python -m projectpulse and a projectpulse console entry point; "
        "include tests for corrupt input, duplicate identifiers, import modes, and CLI exit codes."
    )
    context = {
        "codex_capability_plan_contract": {
            "required_symbols": ["Task", "JSONRepository", "TaskService"],
            "required_paths": [
                "projectpulse/model.py",
                "projectpulse/repository.py",
                "projectpulse/service.py",
                "projectpulse/cli.py",
                "projectpulse/__main__.py",
                "pyproject.toml",
            ],
            "required_entrypoints": ["projectpulse"],
        }
    }

    result = requirement_decision_lane.run_requirement_decision(
        goal, tmp_path, context=context
    )
    behaviors = result["goal_spec"]["acceptance_behaviors"]
    combined = "\n".join(behaviors).lower()

    assert result["status"] == "PASS"
    assert result["goal_spec"]["domain"] == "local_record_cli"
    for required in (
        "status filtering",
        "duplicate task identifiers",
        "import merge",
        "import replace",
        "exit code 0",
        "exit code 2",
        "python -m projectpulse",
        "projectpulse console entry",
    ):
        assert required in combined
    assert len(result["project_plan"]["goal_acceptance_tests"]) == len(behaviors)
    assert len(
        {
            row["test_symbol"]
            for row in result["project_plan"]["goal_acceptance_tests"]
        }
    ) == len(behaviors)
    behavior_tests = next(
        row
        for row in result["project_plan"]["workstreams"]
        if row["id"] == "record_behavior_tests"
    )
    assert behavior_tests["test_intents"] == behaviors


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


def test_explicit_cs2_cli_goal_preserves_domain_capabilities_and_avoids_gui_scope(tmp_path) -> None:
    goal = (
        "Create CS2 Demo Anomaly Lab as a Python CLI. With explicit --allow-network, discover "
        "reviewed public GitLab .dem or 7z candidates, resolve Git LFS hashes, safely download and "
        "extract them, parse real ticks, players, yaw, pitch, weapon_fire, round and death events "
        "with demoparser2, compute spatial and crosshair anomaly windows, treat missing visibility "
        "or sound as unknown, and output JSON plus a local HTML human-review report. The unlabeled "
        "demo proves pipeline execution, not detection accuracy or cheating."
    )
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    discovery = discovery_selection_lane.run_discovery_selection(
        goal,
        tmp_path / "discovery",
        goal_spec=spec,
        project_plan=plan,
    )
    contract = discovery["complexity_project_contract"]
    component_pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        goal,
        {
            "pipeline_plan": {
                "payload": {
                    "component_pipeline": compose_local_pipeline.build_component_pipeline(goal)
                }
            },
            "goal_spec": spec,
            "project_plan": plan,
            "selected_project_direction": discovery["selected_project_direction"],
            "complexity_project_contract": contract,
        },
    )

    assert spec["domain"] == "cs2_demo_anomaly_analysis"
    assert spec["interaction_modes"] == ["cli"]
    assert spec["report_formats"] == ["json", "html"]
    assert spec["runtime_dependencies"] == ["demoparser2", "py7zr"]
    combined = normalized({"spec": spec, "plan": plan})
    for term in (
        "git lfs",
        "safe archive",
        "demoparser2",
        "weapon fire",
        "crosshair",
        "unknown information",
        "human review",
        "accuracy not evaluated",
    ):
        assert term in combined
    assert contract["required_interfaces"] == ["cli"]
    assert contract["report_formats"] == ["json", "html"]
    assert contract["requires_shared_gui_cli_core"] is False
    assert contract["requires_screenshot"] is False
    assert "screenshot" not in contract["required_delivery_evidence"]
    assert "foundation" not in contract["required_pipeline_stages"]
    assert "application_entry" not in contract["required_pipeline_stages"]
    assert "cs2_demo_behavior_tests" not in contract["required_pipeline_stages"]
    assert "delivery" not in contract["required_pipeline_stages"]
    assert discovery["selected_project_direction"]["required_complexity_floor"]["requires_gui"] is False
    assert discovery["selected_project_direction"]["required_complexity_floor"]["requires_screenshot"] is False
    assert "frontend" not in component_pipeline["execution_order"]
    assert component_pipeline["scope_pruning"]["frontend_removed"] is True
    components = {row["id"]: row for row in component_pipeline["components"]}
    assert "tests/test_cs2_demo_behavior_tests.py" in components["tests"]["required_paths"]
    assert "DELIVERY_NOTES.md" in components["docs"]["required_paths"]
    runtime_symbols = component_pipeline["executable_interface_graph"]["stage_callable"]["symbols"]
    assert runtime_symbols == [
        "catalog_and_provenance",
        "bounded_acquisition",
        "demo_parser",
        "geometry_and_information",
        "explainable_anomaly_analysis",
        "human_review_reporting",
        "real_demo_self_test",
    ]
    for component in component_pipeline["components"]:
        for path in component.get("required_paths", []):
            assert run_local_pipeline_impl.component_path_allowed(component["id"], path), (
                component["id"],
                path,
            )
