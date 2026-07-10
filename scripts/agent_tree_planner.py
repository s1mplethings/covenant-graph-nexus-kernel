from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import DEFAULT_EVAL_DIR, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, write_json


def build_agent_tree_dag(shared_context: dict[str, Any]) -> dict[str, Any]:
    project = str(shared_context.get("project_name") or "Local AI Knowledge Studio")
    return {
        "kind": "AgentTreeBuildDAG",
        "project": project,
        "stages": [
            {
                "id": "requirement_freeze",
                "agent": "requirement_agent",
                "depends_on": [],
                "outputs": ["frozen_requirement.json"],
                "verify": ["goal_terms_present", "no_forbidden_context"],
            },
            {
                "id": "foundation",
                "agent": "foundation_leaf",
                "depends_on": ["requirement_freeze"],
                "expected_files": ["README.md", "requirements.txt", "app/main.py"],
                "verify": ["entrypoint_exists", "dependency_file_exists", "startup_command_present"],
            },
            {
                "id": "backend_services",
                "agent": "backend_leaf",
                "depends_on": ["foundation"],
                "expected_files": [
                    "app/services/document_service.py",
                    "app/services/search_service.py",
                    "app/services/model_adapter.py",
                    "app/services/task_service.py",
                    "app/services/report_service.py",
                ],
                "verify": ["service_files_exist", "python_import_smoke"],
            },
            {
                "id": "frontend_views",
                "agent": "frontend_leaf",
                "depends_on": ["backend_services"],
                "expected_files": [
                    "app/templates/dashboard.html",
                    "app/templates/documents.html",
                    "app/templates/search.html",
                    "app/templates/tasks.html",
                    "app/templates/reports.html",
                    "app/templates/settings.html",
                ],
                "verify": ["view_count_ge_5", "frontend_entrypoint_exists"],
            },
            {
                "id": "tests",
                "agent": "test_leaf",
                "depends_on": ["frontend_views"],
                "expected_files": ["tests/test_smoke.py"],
                "verify": ["pytest_exit_code_0"],
            },
            {
                "id": "visual",
                "agent": "qa_agent",
                "depends_on": ["tests"],
                "outputs": ["visual_evidence.json", "screenshots/"],
                "verify": ["screenshots_ge_3", "not_blank_or_placeholder"],
            },
            {
                "id": "delivery",
                "agent": "delivery_agent",
                "depends_on": ["visual"],
                "outputs": ["final_project_bundle.zip"],
                "verify": ["bundle_integrity_pass", "public_delivery_gate_pass"],
            },
        ],
    }


def save_build_dag(dag: dict[str, Any], out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR) -> pathlib.Path:
    return write_json(pathlib.Path(out_dir) / "agent_build_dag.json", dag)


def stage_by_id(dag: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in dag.get("stages", []):
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            return stage
    return {}


def can_execute_stage(dag: dict[str, Any], checkpoints: dict[str, dict[str, Any]], stage_id: str) -> bool:
    stage = stage_by_id(dag, stage_id)
    if not stage:
        return False
    for dep in stage.get("depends_on", []):
        checkpoint = checkpoints.get(dep, {})
        if checkpoint.get("verdict") != "PASS" or not checkpoint.get("can_continue"):
            return False
    return True
