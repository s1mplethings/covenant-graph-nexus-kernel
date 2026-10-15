from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_growth_budget import default_growth_budget, save_growth_budget
    from agent_scope_contract import create_scope_contract, save_scope_contract
    from agent_spawn_protocol import create_spawn_action
    from agent_tree_contracts import write_json
    from agent_tree_registry import add_agent, initial_registry, save_registry
except ModuleNotFoundError:  # pragma: no cover
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


def plan_dynamic_growth(shared_context: dict[str, Any], out_dir: str | pathlib.Path, budget: dict[str, int] | None = None) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "spawn_actions.jsonl").write_text("", encoding="utf-8")
    registry = initial_registry()
    save_registry(registry, out, "agent_tree_registry_initial.json")
    budget_doc = budget or default_growth_budget()
    save_growth_budget(out, budget_doc)

    for branch in BRANCHES:
        _spawn(out, registry, budget_doc, "main_agent", branch, 1)
    for leaf_id, role, files in BACKEND_LEAVES:
        _spawn(out, registry, budget_doc, "backend_branch_agent", (leaf_id, role, f"Create owned backend unit {leaf_id}", ["backend leaf"], files), 2)
    for leaf_id, role, files in FRONTEND_LEAVES:
        _spawn(out, registry, budget_doc, "frontend_branch_agent", (leaf_id, role, f"Create owned frontend page {leaf_id}", ["frontend leaf"], files), 2)
    for leaf_id, role, files in TEST_LEAVES:
        _spawn(out, registry, budget_doc, "test_branch_agent", (leaf_id, role, f"Create owned test unit {leaf_id}", ["test leaf"], files), 2)

    save_registry(registry, out)
    for agent in registry["agents"]:
        agent_id = agent["agent_id"]
        role = agent["role"]
        parent_id = agent.get("parent_id")
        allowed_files = []
        if "Leaf" in role:
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
    write_json(out / "growth_plan_summary.json", {"kind": "DynamicAgentGrowthPlan", "agent_count": len(registry["agents"])})
    return registry
