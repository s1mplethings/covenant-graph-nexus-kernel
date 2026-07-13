from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_project_management import (
        build_performance_snapshot,
        build_project_plan,
        choose_agent_for_task,
        initialize_task_ledger,
        project_health_snapshot,
        record_manager_decision,
        save_project_plan,
        task_statuses_from_ledger,
    )
    from agent_growth_budget import default_growth_budget, save_growth_budget
    from agent_scope_contract import create_scope_contract, save_scope_contract
    from agent_spawn_protocol import create_spawn_action
    from agent_tree_contracts import write_json
    from agent_tree_registry import add_agent, initial_registry, save_registry
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_project_management import (
        build_performance_snapshot,
        build_project_plan,
        choose_agent_for_task,
        initialize_task_ledger,
        project_health_snapshot,
        record_manager_decision,
        save_project_plan,
        task_statuses_from_ledger,
    )
    from scripts.agent_growth_budget import default_growth_budget, save_growth_budget
    from scripts.agent_scope_contract import create_scope_contract, save_scope_contract
    from scripts.agent_spawn_protocol import create_spawn_action
    from scripts.agent_tree_contracts import write_json
    from scripts.agent_tree_registry import add_agent, initial_registry, save_registry


BRANCHES = [
    ("requirement_agent", "RequirementAgent", "Freeze requirements without changing the user goal", ["requirements"], ["frozen_requirement.json"]),
    ("architecture_agent", "ArchitectureAgent", "Plan project architecture and integration contracts", ["architecture"], ["architecture_plan.json"]),
    ("backend_branch_agent", "BackendBranchAgent", "Project requires document import, search, model adapter, task service and report service", ["backend module planning", "backend service coordination"], ["backend_branch_plan.json", "backend_child_agents"]),
    ("frontend_branch_agent", "FrontendBranchAgent", "Project requires dashboard, document, search, task, report and settings views", ["frontend module planning", "frontend page coordination"], ["frontend_branch_plan.json", "frontend_child_agents"]),
    ("test_branch_agent", "TestBranchAgent", "Project requires smoke, backend and UI route tests", ["test planning", "test leaf coordination"], ["test_branch_plan.json", "test_child_agents"]),
    ("integration_agent", "IntegrationAgent", "Project requires integrated runnable entrypoint and config contract", ["integration"], ["integration_result.json"]),
    ("qa_agent", "QAAgent", "Project requires visual and runtime verification", ["qa", "visual evidence"], ["visual_evidence.json"]),
    ("delivery_agent", "DeliveryAgent", "Project requires final package via local_packager and public delivery gate", ["delivery"], ["final_project_bundle.zip"]),
]

BACKEND_LEAVES = [
    ("document_import_leaf", "DocumentImportLeafAgent", ["app/services/storage.py", "app/services/document_import_service.py", "tests/test_document_import_service.py"]),
    ("search_service_leaf", "SearchServiceLeafAgent", ["app/services/search_service.py", "tests/test_search_service.py"]),
    ("model_adapter_leaf", "ModelAdapterLeafAgent", ["app/services/model_adapter.py", "tests/test_model_adapter.py"]),
    ("task_service_leaf", "TaskServiceLeafAgent", ["app/services/task_service.py", "tests/test_task_service.py"]),
    ("report_service_leaf", "ReportServiceLeafAgent", ["app/services/report_service.py", "tests/test_report_service.py"]),
]

FRONTEND_LEAVES = [
    ("dashboard_page_leaf", "DashboardPageLeafAgent", ["app/templates/dashboard.html"]),
    ("documents_page_leaf", "DocumentsPageLeafAgent", ["app/templates/documents.html"]),
    ("search_page_leaf", "SearchPageLeafAgent", ["app/templates/search.html"]),
    ("tasks_page_leaf", "TasksPageLeafAgent", ["app/templates/tasks.html"]),
    ("reports_page_leaf", "ReportsPageLeafAgent", ["app/templates/reports.html"]),
    ("settings_page_leaf", "SettingsPageLeafAgent", ["app/templates/settings.html"]),
]

TEST_LEAVES = [
    ("smoke_test_leaf", "SmokeTestLeafAgent", ["tests/test_smoke.py"]),
    ("backend_tests_leaf", "BackendTestsLeafAgent", ["tests/test_backend_services.py"]),
    ("ui_route_tests_leaf", "UiRouteTestsLeafAgent", ["tests/test_ui_routes.py"]),
]


def _spawn(out_dir: pathlib.Path, registry: dict[str, Any], budget: dict[str, int], parent: str, spec: tuple[str, str, str, list[str], list[str]], depth: int) -> None:
    agent_id, role, reason, scope, outputs = spec
    action = create_spawn_action(
        out_dir=out_dir,
        registry=registry,
        budget=budget,
        parent_agent=parent,
        new_agent_id=agent_id,
        role=role,
        depth=depth,
        reason=reason,
        scope=scope,
        expected_outputs=outputs,
        verification=["scope_contract_valid", "children_within_budget"],
    )
    if action["budget_check"]["allowed"]:
        add_agent(registry, action)


def _project_id(shared_context: dict[str, Any]) -> str:
    raw = str(shared_context.get("project_name") or shared_context.get("user_goal") or "dynamic_project").strip()
    return raw.lower().replace(" ", "_").replace("/", "_")[:80] or "dynamic_project"


def _required_outputs(shared_context: dict[str, Any]) -> list[str]:
    contract = shared_context.get("acceptance_contract")
    outputs: list[str] = []
    if isinstance(contract, dict):
        for key in ("required_outputs", "outputs", "deliverables"):
            value = contract.get(key)
            if isinstance(value, list):
                outputs.extend(str(item) for item in value)
    if not outputs:
        outputs = ["runnable_project", "tests", "visual_evidence", "final_project_bundle.zip"]
    return outputs


def _record_spawn_decision(out: pathlib.Path, registry: dict[str, Any], plan: dict[str, Any], spec: tuple[str, str, str, list[str], list[str]]) -> None:
    agent_id, _role, reason, scope, _outputs = spec
    task = next((item for item in plan.get("work_breakdown_structure", []) if item.get("owner_agent") == agent_id), {})
    if not task:
        task = {
            "task_id": f"spawn_{agent_id}",
            "task_type": "support",
            "priority": "normal",
            "reviewer_agent": "",
        }
    candidates = [{"agent_id": agent_id, "current_load": 0, "critical_path_ready": True}]
    snapshot = build_performance_snapshot(out)
    health = project_health_snapshot(plan.get("work_breakdown_structure", []), task_statuses_from_ledger(out))
    assignment = choose_agent_for_task(task, candidates, snapshot, health)
    record_manager_decision(
        out,
        project_id=str(plan.get("project_id", "")),
        task_id=str(task.get("task_id", "")),
        decision_type="spawn",
        candidate_agents=[agent_id],
        selected_agent=str(assignment.get("selected_agent") or agent_id),
        evidence_used=["project_plan.json", "agent_performance_snapshot.json"],
        performance_snapshot=snapshot,
        project_health_snapshot=health,
        reason=reason,
        resulting_scope=scope,
        resulting_budget={"budget_profile": "growth_budget"},
        required_review_level=str(assignment.get("required_review_level", "normal_review")),
    )


def _role_name(agent_id: str) -> str:
    return "".join(part.capitalize() for part in agent_id.split("_"))


def _task_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(task.get("task_id")): task for task in plan.get("work_breakdown_structure", []) if isinstance(task, dict)}


def _dynamic_agent_specs(plan: dict[str, Any]) -> list[tuple[str, tuple[str, str, str, list[str], list[str]], int]]:
    tasks = [task for task in plan.get("work_breakdown_structure", []) if isinstance(task, dict)]
    by_task = _task_by_id(plan)
    specs: list[tuple[str, tuple[str, str, str, list[str], list[str]], int]] = []
    spawned: set[str] = set()
    for task in sorted(tasks, key=lambda item: int(item.get("estimated_completion_order", 0) or 0)):
        agent_id = str(task.get("owner_agent") or "").strip()
        if not agent_id or agent_id in spawned or agent_id == "main_agent":
            continue
        parent = "main_agent"
        parent_task_id = str(task.get("parent_task_id") or "")
        if parent_task_id and parent_task_id in by_task:
            parent = str(by_task[parent_task_id].get("owner_agent") or "main_agent")
        if parent == agent_id:
            parent = "main_agent"
        depth = 1 if parent == "main_agent" else 2
        role = _role_name(agent_id)
        scope = [str(task.get("task_type", "task")), str(task.get("title", ""))]
        outputs = [str(item) for item in task.get("planned_outputs", [])]
        reason = f"Dynamic WBS task {task.get('task_id')}: {task.get('goal')}"
        specs.append((parent, (agent_id, role, reason, scope, outputs), depth))
        spawned.add(agent_id)
    domain = str(plan.get("domain", ""))
    if "test_branch_agent" in spawned:
        if domain == "knowledge_studio":
            test_specs = TEST_LEAVES
        elif domain == "studio_operations_hub":
            test_specs = [
                ("studio_model_tests_leaf", "StudioModelTestsLeafAgent", ["tests/test_studio_models.py"]),
                ("release_dashboard_tests_leaf", "ReleaseDashboardTestsLeafAgent", ["tests/test_release_dashboard.py"]),
            ]
        elif domain == "media_analysis_tool":
            test_specs = [
                ("media_ingest_tests_leaf", "MediaIngestTestsLeafAgent", ["tests/test_media_ingest.py"]),
                ("batch_report_tests_leaf", "BatchReportTestsLeafAgent", ["tests/test_batch_report.py"]),
            ]
        else:
            test_specs = [("core_tests_leaf", "CoreTestsLeafAgent", ["tests/test_core.py"])]
        for leaf_id, role, files in test_specs:
            if leaf_id not in spawned:
                specs.append(("test_branch_agent", (leaf_id, role, f"Dynamic domain test unit {leaf_id}", ["test leaf", domain], files), 2))
                spawned.add(leaf_id)
    return specs


def _valid_dynamic_specs(specs: list[tuple[str, tuple[str, str, str, list[str], list[str]], int]]) -> bool:
    ids = {spec[1][0] for spec in specs}
    required = {"requirement_agent", "architecture_agent", "integration_agent", "qa_agent", "delivery_agent"}
    return required.issubset(ids) and len(ids) >= 8


def _spawn_static_fallback(out: pathlib.Path, registry: dict[str, Any], budget_doc: dict[str, int], project_plan: dict[str, Any], fallback_reason: str) -> None:
    for branch in BRANCHES:
        _record_spawn_decision(out, registry, project_plan, branch)
        _spawn(out, registry, budget_doc, "main_agent", branch, 1)
    for leaf_id, role, files in BACKEND_LEAVES:
        spec = (leaf_id, role, f"Fallback backend unit {leaf_id}", ["backend leaf"], files)
        _record_spawn_decision(out, registry, project_plan, spec)
        _spawn(out, registry, budget_doc, "backend_branch_agent", spec, 2)
    for leaf_id, role, files in FRONTEND_LEAVES:
        spec = (leaf_id, role, f"Fallback frontend page {leaf_id}", ["frontend leaf"], files)
        _record_spawn_decision(out, registry, project_plan, spec)
        _spawn(out, registry, budget_doc, "frontend_branch_agent", spec, 2)
    for leaf_id, role, files in TEST_LEAVES:
        spec = (leaf_id, role, f"Fallback test unit {leaf_id}", ["test leaf"], files)
        _record_spawn_decision(out, registry, project_plan, spec)
        _spawn(out, registry, budget_doc, "test_branch_agent", spec, 2)
    write_json(out / "dynamic_planner_fallback.json", {"fallback_reason": fallback_reason, "static_template_used": True})


def plan_dynamic_growth(shared_context: dict[str, Any], out_dir: str | pathlib.Path, budget: dict[str, int] | None = None) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "spawn_actions.jsonl").write_text("", encoding="utf-8")
    registry = initial_registry()
    save_registry(registry, out, "agent_tree_registry_initial.json")
    budget_doc = budget or default_growth_budget()
    save_growth_budget(out, budget_doc)
    project_plan = build_project_plan(
        project_id=_project_id(shared_context),
        frozen_goal=str(shared_context.get("user_goal") or shared_context.get("goal") or ""),
        acceptance_contract=shared_context.get("acceptance_contract") or {},
        required_outputs=_required_outputs(shared_context),
        project_budget=budget_doc,
    )
    save_project_plan(out, project_plan)
    initialize_task_ledger(out, list(project_plan.get("work_breakdown_structure", [])))

    fallback_reason = ""
    dynamic_specs = _dynamic_agent_specs(project_plan)
    if _valid_dynamic_specs(dynamic_specs):
        for parent, spec, depth in dynamic_specs:
            _record_spawn_decision(out, registry, project_plan, spec)
            _spawn(out, registry, budget_doc, parent, spec, depth)
    else:
        fallback_reason = "dynamic_wbs_invalid_or_incomplete"
        _spawn_static_fallback(out, registry, budget_doc, project_plan, fallback_reason)

    save_registry(registry, out)
    for agent in registry["agents"]:
        agent_id = agent["agent_id"]
        role = agent["role"]
        parent_id = agent.get("parent_id")
        allowed_files = []
        task = next((item for item in project_plan.get("work_breakdown_structure", []) if item.get("owner_agent") == agent_id), {})
        if task:
            allowed_files = [str(item) for item in task.get("allowed_files", [])]
        elif "Leaf" in role:
            allowed_files = next((files for leaf_id, _, files in BACKEND_LEAVES + FRONTEND_LEAVES + TEST_LEAVES if leaf_id == agent_id), [])
        elif agent_id == "requirement_agent":
            allowed_files = ["frozen_requirement.json"]
        elif agent_id == "architecture_agent":
            allowed_files = ["architecture_plan.json", "api_contract.json", "config/settings.example.env"]
        elif agent_id == "integration_agent":
            allowed_files = ["README.md", "requirements.txt", "app/__init__.py", "app/main.py", "api_contract.json", "config/settings.example.env", "index.html"]
        elif agent_id == "qa_agent":
            allowed_files = ["visual_evidence.json", "screenshots/app_home.png", "screenshots/search_results.png", "screenshots/report_preview.png"]
        elif agent_id == "delivery_agent":
            allowed_files = ["DELIVERY_NOTES.md", "final_project_bundle.zip", "delivery_manifest.json", "packager_run_log.txt"]
        contract = create_scope_contract(agent_id=agent_id, role=role, parent_id=parent_id, allowed_files=allowed_files)
        save_scope_contract(contract, out)
    write_json(
        out / "growth_plan_summary.json",
        {
            "kind": "DynamicAgentGrowthPlan",
            "agent_count": len(registry["agents"]),
            "project_plan_ref": "project_plan.json",
            "task_ledger_ref": "task_ledger.jsonl",
            "manager_decision_ledger_ref": "project_manager_decisions.jsonl",
            "planning_mode": "static_fallback" if fallback_reason else "dynamic_wbs",
            "fallback_reason": fallback_reason,
            "domain": project_plan.get("domain", ""),
        },
    )
    return registry
