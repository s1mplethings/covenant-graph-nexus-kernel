from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import DEFAULT_EVAL_DIR, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, write_json


def build_agent_tree_dag(shared_context: dict[str, Any]) -> dict[str, Any]:
    project = str(shared_context.get("project_name") or "Goal-driven local project")
    project_plan = shared_context.get("project_plan", {})
    if not isinstance(project_plan, dict) or project_plan.get("status") != "PASS":
        return {
            "kind": "AgentTreeBuildDAG",
            "status": "NEEDS_REWORK",
            "reason": "INSUFFICIENT_GOAL_PLAN",
            "project": project,
            "stages": [],
        }
    stages: list[dict[str, Any]] = [
        {
            "id": "requirement_freeze",
            "stage_type": "requirement",
            "agent": "requirement_agent",
            "depends_on": [],
            "outputs": ["frozen_requirement.json"],
            "verify": ["goal_terms_present", "no_forbidden_context"],
        }
    ]
    workstreams = [row for row in project_plan.get("workstreams", []) if isinstance(row, dict)]
    test_stage_ids: list[str] = []
    for workstream in workstreams:
        stage_id = str(workstream.get("id", "")).strip()
        if not stage_id or stage_id == "delivery":
            continue
        is_foundation = stage_id == "foundation"
        is_tests = "test" in stage_id
        dependencies = [str(item) for item in workstream.get("depends_on", [])]
        if is_foundation:
            dependencies = ["requirement_freeze"]
        stages.append(
            {
                "id": stage_id,
                "stage_type": "foundation" if is_foundation else ("tests" if is_tests else "business"),
                "agent": f"{stage_id}_leaf",
                "depends_on": dependencies,
                "expected_files": list(workstream.get("expected_outputs", [])),
                "scope": str(workstream.get("scope", "")),
                "test_intents": list(workstream.get("test_intents", [])),
                "verify": (
                    ["entrypoint_exists", "dependency_file_exists", "startup_command_present"]
                    if is_foundation
                    else (["pytest_exit_code_0"] if is_tests else ["service_files_exist", "python_import_smoke"])
                ),
            }
        )
        if is_tests:
            test_stage_ids.append(stage_id)
    last_stage_id = str(stages[-1]["id"])
    visual_dependency = test_stage_ids[-1] if test_stage_ids else last_stage_id
    stages.append(
        {
            "id": "visual",
            "stage_type": "visual",
            "agent": "qa_agent",
            "depends_on": [visual_dependency],
            "outputs": ["visual_evidence.json", "screenshots/"],
            "verify": ["screenshots_ge_3", "not_blank_or_placeholder"],
        }
    )
    stages.append(
        {
            "id": "delivery",
            "stage_type": "delivery",
            "agent": "delivery_agent",
            "depends_on": ["visual"],
            "outputs": ["final_project_bundle.zip"],
            "verify": ["bundle_integrity_pass", "public_delivery_gate_pass"],
        }
    )
    return {
        "kind": "AgentTreeBuildDAG",
        "status": "PASS",
        "project": project,
        "goal_spec": shared_context.get("goal_spec", {}),
        "project_plan": project_plan,
        "stages": stages,
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
