from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

try:
    from agent_tree_contracts import append_jsonl, now, read_json, read_jsonl, write_json
    from hierarchical_execution import evaluate_authority, make_agent, validate_hierarchy
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import append_jsonl, now, read_json, read_jsonl, write_json
    from scripts.hierarchical_execution import evaluate_authority, make_agent, validate_hierarchy


PERFORMANCE_DIMENSIONS = [
    "quality_score",
    "first_pass_score",
    "scope_discipline_score",
    "delivery_predictability_score",
    "collaboration_score",
    "recovery_score",
    "risk_management_score",
    "trust_score",
    "management_score",
]

QUALITY_WEIGHTS = {
    "quality_score": 0.30,
    "first_pass_score": 0.20,
    "scope_discipline_score": 0.15,
    "delivery_predictability_score": 0.15,
    "collaboration_score": 0.10,
    "risk_management_score": 0.10,
}

EXTERNAL_BLOCKERS = {
    "provider_quota",
    "provider_unavailable",
    "provider_method_unsupported",
    "provider_model_unsupported",
    "network_transient",
    "user_changed_requirement",
    "parent_bad_scope",
}

HIGH_SEVERITY_EVENTS = {"scope_violation", "false_success", "hidden_failure", "unsupported_claim"}
MANAGEMENT_FAULTS = {"bad_split", "oversized_scope", "missing_dependency", "bad_estimate", "unsafe_parallel", "missing_reviewer", "ignored_critical_risk"}


def risk_context_from_task(
    *,
    run_id: str,
    project_id: str,
    task: dict[str, Any],
    health: dict[str, Any],
    performance_snapshot: dict[str, Any],
    budget_remaining: int,
    circuit_state: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "project_id": project_id,
        "task_id": task.get("task_id", ""),
        "task_type": task.get("task_type", ""),
        "risk_level": task.get("risk_level", "medium"),
        "critical_path": bool(task.get("critical_path", False)),
        "health_status": health.get("status", "unknown"),
        "performance_agents": sorted((performance_snapshot.get("agents") or {}).keys()) if isinstance(performance_snapshot.get("agents"), dict) else [],
        "budget_remaining": int(budget_remaining),
        "circuit_state": circuit_state,
    }


def dispatch_risk_selected(risk_context: dict[str, Any], *, ledger_path: str | pathlib.Path) -> dict[str, Any]:
    high_risk = str(risk_context.get("risk_level", "")).lower() in {"high", "critical"}
    blocked_provider = risk_context.get("circuit_state") not in {"", "closed"}
    selected_mode = "manager_review" if high_risk or blocked_provider or risk_context.get("critical_path") else "standard_replan"
    raw_id = json.dumps(risk_context, ensure_ascii=False, sort_keys=True, default=str)
    decision = {
        "kind": "risk_selected_pm_decision",
        "decision_id": f"risk_{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:12]}",
        "run_id": risk_context.get("run_id", ""),
        "project_id": risk_context.get("project_id", ""),
        "task_id": risk_context.get("task_id", ""),
        "selected_mode": selected_mode,
        "selected_challengers": ["manager_review"] if selected_mode == "manager_review" else [],
        "risk_context": risk_context,
        "created_at": now(),
    }
    append_jsonl(pathlib.Path(ledger_path), decision)
    return decision


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _score(value: Any, default: float = 0.72) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def project_management_paths(out_dir: str | pathlib.Path) -> dict[str, pathlib.Path]:
    out = pathlib.Path(out_dir)
    return {
        "project_plan": out / "project_plan.json",
        "task_ledger": out / "task_ledger.jsonl",
        "performance_ledger": out / "agent_performance_ledger.jsonl",
        "manager_decisions": out / "project_manager_decisions.jsonl",
        "performance_snapshot": out / "agent_performance_snapshot.json",
        "project_health": out / "project_health.json",
        "project_health_history": out / "project_health_history.jsonl",
        "api_comparison": out / "api_governance_comparison.json",
    }


def build_project_plan(
    *,
    project_id: str,
    frozen_goal: str,
    acceptance_contract: dict[str, Any] | list[Any] | None = None,
    required_outputs: list[str] | None = None,
    project_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs = [str(item) for item in _list(required_outputs)] or [
        "frozen_requirement.json",
        "architecture_plan.json",
        "runnable_project",
        "tests",
        "visual_evidence",
        "final_project_bundle.zip",
    ]
    domain = infer_project_domain(frozen_goal, acceptance_contract or {}, outputs)
    milestones = [
        {"milestone_id": "m1_requirements", "title": "Freeze requirement and acceptance", "required_outputs": ["frozen_requirement.json"]},
        {"milestone_id": "m2_architecture", "title": "Plan architecture and dependencies", "required_outputs": ["architecture_plan.json", "api_contract.json"]},
        {"milestone_id": f"m3_{domain}_build", "title": f"Build scoped {domain} work packages", "required_outputs": outputs},
        {"milestone_id": "m4_integrate", "title": "Integrate runnable project", "required_outputs": ["app/main.py", "requirements.txt"]},
        {"milestone_id": "m5_evidence", "title": "Collect test and visual evidence", "required_outputs": ["TEST_REPORT.md", "visual_evidence.json"]},
        {"milestone_id": "m6_package", "title": "Package through local_packager and public gate", "required_outputs": ["final_project_bundle.zip", "delivery_manifest.json"]},
    ]
    tasks = derive_task_contracts(
        project_id=project_id,
        frozen_goal=frozen_goal,
        acceptance_contract=acceptance_contract or {},
        required_outputs=outputs,
        project_budget=project_budget or {},
    )
    critical_path = compute_critical_path(tasks)
    timestamp = now()
    return {
        "kind": "DynamicAgentProjectPlan",
        "project_id": project_id,
        "frozen_goal": frozen_goal,
        "domain": domain,
        "milestones": milestones,
        "work_breakdown_structure": tasks,
        "critical_path": critical_path,
        "dependencies": {task["task_id"]: task["dependency_task_ids"] for task in tasks},
        "project_budget": dict(project_budget or {}),
        "risk_register_ref": "CFO_RISK_REGISTER.md",
        "acceptance_contract_ref": "frozen_requirement.json",
        "current_stage": "planning",
        "health_status": "green",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def derive_task_contracts(
    *,
    project_id: str,
    frozen_goal: str,
    acceptance_contract: dict[str, Any] | list[Any],
    required_outputs: list[str],
    project_budget: dict[str, Any],
) -> list[dict[str, Any]]:
    goal_text = frozen_goal.lower()
    acceptance_text = json.dumps(acceptance_contract, ensure_ascii=False).lower()
    domain = infer_project_domain(frozen_goal, acceptance_contract, required_outputs)
    tasks: list[dict[str, Any]] = [
        _task(project_id, "task_requirements", None, "Freeze requirements", "requirements", "requirement_agent", "architecture_agent", [], ["frozen_requirement.json"], ["frozen_requirement.json"], 1, 1800, 1),
        _task(project_id, "task_architecture", None, "Architecture and dependency plan", "architecture", "architecture_agent", "integration_agent", ["task_requirements"], ["architecture_plan.json", "api_contract.json"], ["architecture_plan.json", "api_contract.json"], 1, 2200, 2),
    ]
    if domain == "knowledge_studio":
        tasks.extend(_knowledge_studio_tasks(project_id))
    elif domain == "studio_operations_hub":
        tasks.extend(_studio_operations_tasks(project_id))
    elif domain == "media_analysis_tool":
        tasks.extend(_media_analysis_tasks(project_id))
    else:
        tasks.extend(_generic_product_tasks(project_id))
    order = max(int(task["estimated_completion_order"]) for task in tasks) + 1
    tasks.extend(
        [
            _task(project_id, "task_tests", None, "Test evidence", "test", "test_branch_agent", "qa_agent", _build_task_ids(tasks), ["tests/"], ["tests/"], 2, 2500, order),
            _task(project_id, "task_integration", None, "Runnable integration", "integration", "integration_agent", "qa_agent", _build_task_ids(tasks) + ["task_tests"], ["app/main.py", "requirements.txt"], ["app/main.py", "requirements.txt", "README.md"], 1, 2200, order + 1),
            _task(project_id, "task_qa", None, "Quality and visual evidence", "qa", "qa_agent", "delivery_agent", ["task_integration"], ["TEST_REPORT.md", "visual_evidence.json"], ["TEST_REPORT.md", "visual_evidence.json", "screenshots/"], 1, 1800, order + 2),
            _task(project_id, "task_delivery", None, "Package delivery", "delivery", "delivery_agent", "main_agent", ["task_qa"], ["final_project_bundle.zip", "delivery_manifest.json"], ["DELIVERY_NOTES.md", "final_project_bundle.zip", "delivery_manifest.json"], 1, 1200, order + 3),
        ]
    )
    return tasks


def infer_project_domain(frozen_goal: str, acceptance_contract: dict[str, Any] | list[Any], required_outputs: list[str]) -> str:
    text = " ".join([frozen_goal, json.dumps(acceptance_contract, ensure_ascii=False), " ".join(required_outputs)]).lower()
    if any(marker in text for marker in ("media", "video", "audio", "批量媒体", "媒体分析", "transcript", "clip", "素材")):
        return "media_analysis_tool"
    if any(marker in text for marker in ("game studio", "游戏工作室", "production", "生产管理", "milestone", "asset pipeline", "独立游戏")):
        return "studio_operations_hub"
    if any(marker in text for marker in ("knowledge", "知识", "search", "检索", "ai", "model", "模型", "工作台")):
        return "knowledge_studio"
    return "generic_product"


def _build_task_ids(tasks: list[dict[str, Any]]) -> list[str]:
    return [str(task["task_id"]) for task in tasks if str(task.get("task_id", "")).startswith("task_") and task["task_id"] not in {"task_requirements", "task_architecture"}]


def _knowledge_studio_tasks(project_id: str) -> list[dict[str, Any]]:
    return [
        _task(project_id, "task_backend", None, "Knowledge backend services", "knowledge_backend", "backend_branch_agent", "integration_agent", ["task_architecture"], ["app/services/storage.py"], ["app/services/", "tests/"], 3, 4500, 3),
        _task(project_id, "task_document_import", "task_backend", "Document import and storage", "document_import", "document_import_leaf", "backend_branch_agent", ["task_backend"], ["app/services/document_import_service.py"], ["app/services/storage.py", "app/services/document_import_service.py", "tests/test_document_import_service.py"], 1, 1500, 4),
        _task(project_id, "task_knowledge_search", "task_backend", "Knowledge search service", "knowledge_search", "search_service_leaf", "backend_branch_agent", ["task_document_import"], ["app/services/search_service.py"], ["app/services/search_service.py", "tests/test_search_service.py"], 1, 1500, 5),
        _task(project_id, "task_model_adapter", "task_backend", "Local model adapter", "model_adapter", "model_adapter_leaf", "backend_branch_agent", ["task_backend"], ["app/services/model_adapter.py"], ["app/services/model_adapter.py", "tests/test_model_adapter.py"], 1, 1600, 5),
        _task(project_id, "task_task_tracking", "task_backend", "Task tracking service", "task_tracking", "task_service_leaf", "backend_branch_agent", ["task_knowledge_search"], ["app/services/task_service.py"], ["app/services/task_service.py", "tests/test_task_service.py"], 1, 1500, 6),
        _task(project_id, "task_report_builder", "task_backend", "Knowledge report builder", "report_builder", "report_service_leaf", "backend_branch_agent", ["task_task_tracking"], ["app/services/report_service.py"], ["app/services/report_service.py", "tests/test_report_service.py"], 1, 1500, 7),
        _task(project_id, "task_frontend", None, "Knowledge workspace views", "knowledge_frontend", "frontend_branch_agent", "integration_agent", ["task_architecture"], ["app/templates/dashboard.html"], ["app/templates/", "index.html"], 2, 3200, 4),
        _task(project_id, "task_dashboard_view", "task_frontend", "Dashboard workspace view", "dashboard_view", "dashboard_page_leaf", "frontend_branch_agent", ["task_frontend"], ["app/templates/dashboard.html"], ["app/templates/dashboard.html"], 1, 900, 5),
        _task(project_id, "task_documents_view", "task_frontend", "Documents workspace view", "documents_view", "documents_page_leaf", "frontend_branch_agent", ["task_frontend"], ["app/templates/documents.html"], ["app/templates/documents.html"], 1, 900, 5),
        _task(project_id, "task_search_view", "task_frontend", "Search workspace view", "search_view", "search_page_leaf", "frontend_branch_agent", ["task_frontend"], ["app/templates/search.html"], ["app/templates/search.html"], 1, 900, 6),
        _task(project_id, "task_tasks_view", "task_frontend", "Tasks workspace view", "tasks_view", "tasks_page_leaf", "frontend_branch_agent", ["task_frontend"], ["app/templates/tasks.html"], ["app/templates/tasks.html"], 1, 900, 6),
        _task(project_id, "task_reports_view", "task_frontend", "Reports workspace view", "reports_view", "reports_page_leaf", "frontend_branch_agent", ["task_frontend"], ["app/templates/reports.html"], ["app/templates/reports.html"], 1, 900, 7),
        _task(project_id, "task_settings_view", "task_frontend", "Settings workspace view", "settings_view", "settings_page_leaf", "frontend_branch_agent", ["task_frontend"], ["app/templates/settings.html"], ["app/templates/settings.html"], 1, 900, 7),
    ]


def _studio_operations_tasks(project_id: str) -> list[dict[str, Any]]:
    return [
        _task(project_id, "task_ops_data_model", None, "Studio production data model", "studio_data", "studio_data_branch_agent", "integration_agent", ["task_architecture"], ["app/studio/models.py"], ["app/studio/models.py", "tests/test_studio_models.py"], 2, 2600, 3),
        _task(project_id, "task_milestone_planning", "task_ops_data_model", "Milestone and sprint planning", "milestone_planning", "studio_milestone_leaf", "studio_data_branch_agent", ["task_ops_data_model"], ["app/studio/milestones.py"], ["app/studio/milestones.py", "tests/test_milestones.py"], 1, 1500, 4),
        _task(project_id, "task_asset_pipeline", "task_ops_data_model", "Asset pipeline and review queue", "asset_pipeline", "studio_asset_pipeline_leaf", "studio_data_branch_agent", ["task_ops_data_model"], ["app/studio/assets.py"], ["app/studio/assets.py", "tests/test_assets.py"], 1, 1700, 5),
        _task(project_id, "task_capacity_budget", "task_ops_data_model", "Team capacity and budget forecast", "capacity_budget", "studio_capacity_leaf", "studio_data_branch_agent", ["task_milestone_planning"], ["app/studio/capacity.py"], ["app/studio/capacity.py", "tests/test_capacity.py"], 1, 1600, 6),
        _task(project_id, "task_release_readiness", None, "Release readiness dashboard", "release_dashboard", "studio_release_dashboard_leaf", "qa_agent", ["task_asset_pipeline", "task_capacity_budget"], ["app/templates/release_dashboard.html"], ["app/templates/release_dashboard.html", "tests/test_release_dashboard.py"], 1, 1600, 7),
    ]


def _media_analysis_tasks(project_id: str) -> list[dict[str, Any]]:
    return [
        _task(project_id, "task_media_ingest", None, "Batch media ingest manifest", "media_ingest", "media_ingest_leaf", "integration_agent", ["task_architecture"], ["app/media/ingest.py"], ["app/media/ingest.py", "tests/test_media_ingest.py"], 1, 1500, 3),
        _task(project_id, "task_metadata_analysis", "task_media_ingest", "Metadata and transcript analysis", "metadata_analysis", "media_metadata_analysis_leaf", "media_ingest_leaf", ["task_media_ingest"], ["app/media/analyze.py"], ["app/media/analyze.py", "tests/test_metadata_analysis.py"], 2, 2200, 4),
        _task(project_id, "task_batch_report", "task_metadata_analysis", "Batch report generation", "batch_report", "media_batch_report_leaf", "integration_agent", ["task_metadata_analysis"], ["app/media/report.py"], ["app/media/report.py", "tests/test_batch_report.py"], 1, 1700, 5),
        _task(project_id, "task_export_pack", "task_batch_report", "CSV/HTML export package", "media_export", "media_export_pack_leaf", "delivery_agent", ["task_batch_report"], ["app/media/export.py"], ["app/media/export.py", "tests/test_media_export.py"], 1, 1400, 6),
    ]


def _generic_product_tasks(project_id: str) -> list[dict[str, Any]]:
    return [
        _task(project_id, "task_core_module", None, "Core product module", "core_module", "core_branch_agent", "integration_agent", ["task_architecture"], ["app/core.py"], ["app/core.py", "tests/test_core.py"], 2, 2500, 3),
        _task(project_id, "task_user_surface", None, "User-facing surface", "user_surface", "surface_agent", "qa_agent", ["task_core_module"], ["app/ui.py"], ["app/ui.py", "tests/test_ui.py"], 1, 1800, 4),
    ]


def _task(
    project_id: str,
    task_id: str,
    parent_task_id: str | None,
    title: str,
    task_type: str,
    owner_agent: str,
    reviewer_agent: str,
    dependencies: list[str],
    outputs: list[str],
    allowed_files: list[str],
    estimated_api_calls: int,
    estimated_prompt_budget: int,
    order: int,
) -> dict[str, Any]:
    timestamp = now()
    return {
        "task_id": task_id,
        "project_id": project_id,
        "parent_task_id": parent_task_id,
        "title": title,
        "goal": title,
        "task_type": task_type,
        "owner_agent": owner_agent,
        "owner_role_requirements": [task_type, "scope_discipline", "evidence_delivery"],
        "reviewer_agent": reviewer_agent,
        "priority": "critical" if task_type in {"requirements", "architecture", "integration", "delivery"} else "normal",
        "dependency_task_ids": dependencies,
        "planned_outputs": outputs,
        "allowed_files": allowed_files,
        "forbidden_files": ["delivery_manifest.json", "final_project_bundle.zip"] if task_type not in {"delivery"} else [],
        "acceptance_criteria": [f"{title} has concrete evidence", "scope contract respected"],
        "evidence_requirements": ["checkpoint", "ledger_event", "owned_outputs"],
        "estimated_api_calls": estimated_api_calls,
        "estimated_prompt_budget": estimated_prompt_budget,
        "estimated_completion_order": order,
        "project_stage": "build" if order >= 3 else "planning",
        "review_level": "independent" if task_type in {"integration", "delivery", "release_dashboard"} else "normal",
        "completion_condition": "all planned outputs exist, focused checks pass, evidence ledger updated",
        "status": "pending",
        "blockers": [],
        "retry_count": 0,
        "started_at": "",
        "updated_at": timestamp,
        "completed_at": "",
    }


def compute_critical_path(tasks: list[dict[str, Any]]) -> list[str]:
    by_id = {str(task["task_id"]): task for task in tasks}
    memo: dict[str, list[str]] = {}

    def best_path(task_id: str) -> list[str]:
        if task_id in memo:
            return memo[task_id]
        task = by_id.get(task_id, {})
        deps = [dep for dep in _list(task.get("dependency_task_ids")) if dep in by_id]
        if not deps:
            memo[task_id] = [task_id]
            return memo[task_id]
        prefix = max((best_path(dep) for dep in deps), key=len)
        memo[task_id] = prefix + [task_id]
        return memo[task_id]

    if not by_id:
        return []
    return max((best_path(task_id) for task_id in by_id), key=len)


def save_project_plan(out_dir: str | pathlib.Path, plan: dict[str, Any]) -> pathlib.Path:
    return write_json(project_management_paths(out_dir)["project_plan"], plan)


def initialize_task_ledger(out_dir: str | pathlib.Path, tasks: list[dict[str, Any]]) -> None:
    path = project_management_paths(out_dir)["task_ledger"]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for task in tasks:
        append_task_event(out_dir, task, "created", reason="project_plan")


def append_task_event(out_dir: str | pathlib.Path, task: dict[str, Any], event_type: str, *, status: str | None = None, reason: str = "", evidence_refs: list[str] | None = None) -> dict[str, Any]:
    event = {
        "event_id": _stable_id("task_event", {"task_id": task.get("task_id"), "event_type": event_type, "status": status or task.get("status"), "created_at": now(), "reason": reason}),
        "project_id": task.get("project_id", ""),
        "task_id": task.get("task_id", ""),
        "parent_task_id": task.get("parent_task_id"),
        "owner_agent": task.get("owner_agent", ""),
        "reviewer_agent": task.get("reviewer_agent", ""),
        "event_type": event_type,
        "status": status or task.get("status", ""),
        "dependency_task_ids": list(task.get("dependency_task_ids", [])),
        "evidence_refs": list(evidence_refs or []),
        "reason": reason,
        "created_at": now(),
    }
    append_jsonl(project_management_paths(out_dir)["task_ledger"], event)
    return event


def task_statuses_from_ledger(out_dir: str | pathlib.Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for event in read_jsonl(project_management_paths(out_dir)["task_ledger"]):
        if isinstance(event, dict) and event.get("task_id"):
            statuses[str(event["task_id"])] = str(event.get("status") or "")
    return statuses


def can_start_task(task: dict[str, Any], statuses: dict[str, str]) -> dict[str, Any]:
    missing = [str(dep) for dep in task.get("dependency_task_ids", []) if statuses.get(str(dep)) != "completed"]
    return {
        "can_start": not missing,
        "blocked_dependencies": missing,
        "reason": "" if not missing else "dependencies_not_completed",
    }


def record_performance_event(
    out_dir: str | pathlib.Path,
    *,
    agent_id: str,
    task_id: str,
    task_type: str,
    event_type: str,
    controllability: str = "controllable",
    evidence_refs: list[str] | None = None,
    first_pass: bool | None = None,
    repair_count: int = 0,
    scope_violations: int = 0,
    handoff_quality: float = 0.7,
    integration_rework: int = 0,
    budget_variance: float = 0.0,
    schedule_variance: float = 0.0,
    risk_discovery: int = 0,
    false_success_attempt: bool = False,
    external_blocker: str = "",
    score_delta: float | None = None,
    reason: str = "",
) -> dict[str, Any]:
    external = external_blocker or (event_type if event_type in EXTERNAL_BLOCKERS else "")
    if external:
        controllability = "external"
    if score_delta is None:
        score_delta = infer_score_delta(
            event_type=event_type,
            controllability=controllability,
            first_pass=first_pass,
            scope_violations=scope_violations,
            false_success_attempt=false_success_attempt,
            repair_count=repair_count,
            integration_rework=integration_rework,
        )
    event = {
        "agent_id": agent_id,
        "task_id": task_id,
        "task_type": task_type,
        "event_type": event_type,
        "controllability": controllability,
        "evidence_refs": list(evidence_refs or []),
        "first_pass": first_pass,
        "repair_count": repair_count,
        "scope_violations": scope_violations,
        "handoff_quality": handoff_quality,
        "integration_rework": integration_rework,
        "budget_variance": budget_variance,
        "schedule_variance": schedule_variance,
        "risk_discovery": risk_discovery,
        "false_success_attempt": false_success_attempt,
        "external_blocker": external,
        "score_delta": score_delta,
        "reason": reason,
        "created_at": now(),
    }
    append_jsonl(project_management_paths(out_dir)["performance_ledger"], event)
    write_json(project_management_paths(out_dir)["performance_snapshot"], build_performance_snapshot(out_dir))
    return event


def infer_score_delta(
    *,
    event_type: str,
    controllability: str,
    first_pass: bool | None,
    scope_violations: int,
    false_success_attempt: bool,
    repair_count: int,
    integration_rework: int,
) -> float:
    if controllability == "external" or event_type in EXTERNAL_BLOCKERS:
        return 0.0
    if false_success_attempt or event_type == "false_success":
        return -0.35
    if scope_violations or event_type == "scope_violation":
        return -0.22
    if event_type in MANAGEMENT_FAULTS:
        return -0.18
    if event_type == "task_completed":
        delta = 0.14 if first_pass else 0.06
        return max(-0.1, delta - 0.04 * repair_count - 0.05 * integration_rework)
    if event_type == "handoff_accepted":
        return 0.06
    if event_type == "risk_discovered":
        return 0.05
    if event_type == "task_failed":
        return -0.08
    return 0.0


def build_performance_snapshot(out_dir: str | pathlib.Path) -> dict[str, Any]:
    agents: dict[str, dict[str, Any]] = {}
    for event in read_jsonl(project_management_paths(out_dir)["performance_ledger"]):
        if not isinstance(event, dict):
            continue
        agent_id = str(event.get("agent_id", ""))
        if not agent_id:
            continue
        profile = agents.setdefault(
            agent_id,
            {
                "agent_id": agent_id,
                **{dimension: 0.72 for dimension in PERFORMANCE_DIMENSIONS},
                "task_type_successes": {},
                "current_load": 0,
                "preferred_task_types": [],
                "cooldowns": {},
                "intervention_level": 0,
                "event_count": 0,
            },
        )
        profile["event_count"] += 1
        event_type = str(event.get("event_type", ""))
        if str(event.get("controllability")) == "external" or event.get("external_blocker"):
            continue
        delta = float(event.get("score_delta") or 0.0)
        if event_type == "task_completed":
            profile["quality_score"] = _score(profile["quality_score"] + delta * 0.8)
            profile["first_pass_score"] = _score(profile["first_pass_score"] + (0.10 if event.get("first_pass") else -0.04))
            task_type = str(event.get("task_type", "general"))
            successes = profile.setdefault("task_type_successes", {})
            successes[task_type] = int(successes.get(task_type, 0)) + 1
            if successes[task_type] >= 2 and task_type not in profile["preferred_task_types"]:
                profile["preferred_task_types"].append(task_type)
        elif event_type in {"scope_violation", "false_success", "hidden_failure", "unsupported_claim"}:
            profile["scope_discipline_score"] = _score(profile["scope_discipline_score"] + delta)
            profile["trust_score"] = _score(profile["trust_score"] + delta)
            profile["intervention_level"] = max(int(profile.get("intervention_level", 0)), 3 if event_type == "false_success" else 2)
        elif event_type in MANAGEMENT_FAULTS:
            profile["management_score"] = _score(profile["management_score"] + delta)
            profile["trust_score"] = _score(profile["trust_score"] + delta / 2)
        elif event_type == "handoff_accepted":
            profile["collaboration_score"] = _score(profile["collaboration_score"] + delta)
        elif event_type == "risk_discovered":
            profile["risk_management_score"] = _score(profile["risk_management_score"] + delta)
        elif event_type == "task_failed":
            profile["recovery_score"] = _score(profile["recovery_score"] + delta)
            profile["intervention_level"] = max(int(profile.get("intervention_level", 0)), 1)
        profile["delivery_predictability_score"] = _score(profile["delivery_predictability_score"] - abs(float(event.get("budget_variance") or 0.0)) * 0.03 - abs(float(event.get("schedule_variance") or 0.0)) * 0.03)
        profile["overall_score"] = weighted_agent_score(profile)
    for profile in agents.values():
        profile.setdefault("overall_score", weighted_agent_score(profile))
    return {"kind": "AgentPerformanceSnapshot", "agents": agents, "created_at": now()}


def weighted_agent_score(profile: dict[str, Any]) -> float:
    value = sum(_score(profile.get(key)) * weight for key, weight in QUALITY_WEIGHTS.items())
    return round(max(0.0, min(1.0, value)), 4)


def choose_agent_for_task(
    task: dict[str, Any],
    candidate_agents: list[dict[str, Any]],
    performance_snapshot: dict[str, Any],
    project_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agents = performance_snapshot.get("agents", {}) if isinstance(performance_snapshot, dict) else {}
    critical = bool(project_health and str(project_health.get("critical_path_health")) == "red") or task.get("priority") == "critical"
    scored: list[dict[str, Any]] = []
    for candidate in candidate_agents:
        agent_id = str(candidate.get("agent_id", ""))
        if not agent_id:
            continue
        profile = dict(agents.get(agent_id, {}))
        task_type = str(task.get("task_type", "general"))
        successes = int(profile.get("task_type_successes", {}).get(task_type, 0)) if isinstance(profile.get("task_type_successes"), dict) else 0
        load = int(profile.get("current_load", candidate.get("current_load", 0)) or 0)
        reviewer_conflict = bool(task.get("risk_level") == "high" and task.get("reviewer_agent") == agent_id)
        score = weighted_agent_score(profile or {})
        score += min(0.12, successes * 0.04)
        score += 0.05 if task_type in set(profile.get("preferred_task_types", [])) else 0.0
        score -= min(0.30, load * 0.10)
        score -= 0.20 if reviewer_conflict else 0.0
        score += 0.04 if critical and candidate.get("critical_path_ready", True) else 0.0
        scored.append(
            {
                "agent_id": agent_id,
                "score": round(score, 5),
                "load": load,
                "successes": successes,
                "reviewer_conflict": reviewer_conflict,
                "intervention_level": int(profile.get("intervention_level", 0) or 0),
            }
        )
    scored.sort(key=lambda item: (-item["score"], item["load"], item["agent_id"]))
    selected = scored[0] if scored else {"agent_id": "", "score": 0}
    review_level = "senior_review" if task.get("risk_level") == "high" or selected.get("intervention_level", 0) >= 2 else "normal_review"
    return {"selected_agent": selected.get("agent_id", ""), "scored_candidates": scored, "required_review_level": review_level}


def record_manager_decision(
    out_dir: str | pathlib.Path,
    *,
    project_id: str,
    task_id: str,
    decision_type: str,
    candidate_agents: list[str],
    selected_agent: str,
    evidence_used: list[str],
    performance_snapshot: dict[str, Any],
    project_health_snapshot: dict[str, Any],
    reason: str,
    alternatives_rejected: list[str] | None = None,
    resulting_scope: list[str] | None = None,
    resulting_budget: dict[str, Any] | None = None,
    required_review_level: str = "normal_review",
) -> dict[str, Any]:
    decision = {
        "decision_id": _stable_id("pm_decision", {"project_id": project_id, "task_id": task_id, "decision_type": decision_type, "selected_agent": selected_agent, "created_at": now()}),
        "project_id": project_id,
        "task_id": task_id,
        "decision_type": decision_type,
        "candidate_agents": list(candidate_agents),
        "selected_agent": selected_agent,
        "evidence_used": list(evidence_used),
        "performance_snapshot": performance_snapshot,
        "project_health_snapshot": project_health_snapshot,
        "reason": reason,
        "alternatives_rejected": list(alternatives_rejected or []),
        "resulting_scope": list(resulting_scope or []),
        "resulting_budget": dict(resulting_budget or {}),
        "required_review_level": required_review_level,
        "created_at": now(),
    }
    append_jsonl(project_management_paths(out_dir)["manager_decisions"], decision)
    return decision


def evaluate_intervention(profile: dict[str, Any], recent_events: list[dict[str, Any]]) -> dict[str, Any]:
    controllable_failures = [event for event in recent_events if event.get("controllability") != "external" and event.get("event_type") in {"task_failed", "scope_violation", "false_success"}]
    false_success = any(event.get("event_type") == "false_success" or event.get("false_success_attempt") for event in recent_events)
    scope_violations = sum(int(event.get("scope_violations") or 0) for event in recent_events)
    if false_success:
        level = 4 if len(controllable_failures) >= 2 else 3
    elif len(controllable_failures) >= 4:
        level = 5
    elif len(controllable_failures) >= 3:
        level = 4
    elif scope_violations or len(controllable_failures) == 2:
        level = 2
    elif controllable_failures:
        level = 1
    else:
        level = 0
    actions = {
        0: ["normal_execution"],
        1: ["require_explicit_plan", "checkpoint"],
        2: ["shrink_scope", "force_reviewer"],
        3: ["split_or_reassign"],
        4: ["replace_owner", "assign_postmortem"],
        5: ["prune"],
    }[level]
    return {"intervention_level": level, "actions": actions, "reason": "controllable_failure_pattern" if level else "healthy"}


def reward_authorization(profile: dict[str, Any], task_type: str) -> dict[str, Any]:
    successes = int(profile.get("task_type_successes", {}).get(task_type, 0)) if isinstance(profile.get("task_type_successes"), dict) else 0
    trust = _score(profile.get("trust_score"))
    cooldown = int(profile.get("cooldowns", {}).get(task_type, 0)) if isinstance(profile.get("cooldowns"), dict) else 0
    if successes < 2 or trust < 0.70 or cooldown > 0:
        return {"actions": [], "cap": "no_change", "reason": "insufficient_evidence_or_cooldown"}
    actions = ["preferred_for_similar_tasks", "increase_budget_within_cap"]
    if successes >= 3 and trust >= 0.82:
        actions.append("reduce_intermediate_review")
    if successes >= 4 and trust >= 0.88:
        actions.extend(["promote_to_branch_lead", "allow_parallel_subtasks"])
    return {"actions": actions, "cap": "bounded", "cooldown_after_use": 2, "reason": "repeated_evidence_backed_success"}


def parent_management_responsibility(
    *,
    parent_agent: str,
    child_task: dict[str, Any],
    failure_reason: str,
    evidence_refs: list[str] | None = None,
    out_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    reason = failure_reason if failure_reason in MANAGEMENT_FAULTS else "bad_split"
    event = {
        "parent_agent": parent_agent,
        "child_task_id": child_task.get("task_id", ""),
        "event_type": reason,
        "management_responsibility": True,
        "evidence_refs": list(evidence_refs or []),
        "created_at": now(),
    }
    if out_dir is not None:
        record_performance_event(
            out_dir,
            agent_id=parent_agent,
            task_id=str(child_task.get("task_id", "")),
            task_type="management",
            event_type=reason,
            evidence_refs=list(evidence_refs or []),
            reason=f"parent responsibility for {failure_reason}",
        )
    return event


def project_health_snapshot(tasks: list[dict[str, Any]], statuses: dict[str, str], budget_state: dict[str, Any] | None = None, provider_state: dict[str, Any] | None = None) -> dict[str, Any]:
    total = max(1, len(tasks))
    completed = sum(1 for task in tasks if statuses.get(str(task.get("task_id"))) == "completed")
    blocked = sum(1 for task in tasks if statuses.get(str(task.get("task_id"))) == "blocked")
    budget_exhausted = bool(budget_state and budget_state.get("blocked"))
    provider_blocked = bool(provider_state and provider_state.get("circuit_state") == "open")
    critical_path = compute_critical_path(tasks)
    critical_blocked = any(statuses.get(task_id) == "blocked" for task_id in critical_path)
    return {
        "scope_health": "red" if blocked else "green",
        "schedule_health": "red" if critical_blocked else ("yellow" if completed / total < 0.35 else "green"),
        "budget_health": "red" if budget_exhausted else "green",
        "integration_health": "yellow" if statuses.get("task_integration") not in {"completed", ""} else "green",
        "quality_health": "yellow" if statuses.get("task_qa") not in {"completed", ""} else "green",
        "provider_health": "red" if provider_blocked else "green",
        "delivery_health": "green" if statuses.get("task_delivery") == "completed" else "yellow",
        "critical_path_health": "red" if critical_blocked else "green",
        "completed_ratio": round(completed / total, 4),
        "blocked_count": blocked,
        "created_at": now(),
    }


def run_project_manager_cycle(
    out_dir: str | pathlib.Path,
    *,
    budget_state: dict[str, Any] | None = None,
    provider_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = read_json(project_management_paths(out_dir)["project_plan"], {})
    tasks = plan.get("work_breakdown_structure", []) if isinstance(plan, dict) else []
    tasks = [task for task in tasks if isinstance(task, dict)]
    statuses = task_statuses_from_ledger(out_dir)
    snapshot = build_performance_snapshot(out_dir)
    health = project_health_snapshot(tasks, statuses, budget_state=budget_state, provider_state=provider_state)
    write_json(project_management_paths(out_dir)["project_health"], health)
    append_jsonl(project_management_paths(out_dir)["project_health_history"], health)

    performance_events = [event for event in read_jsonl(project_management_paths(out_dir)["performance_ledger"]) if isinstance(event, dict)]
    actions: list[dict[str, Any]] = []
    critical_path = compute_critical_path(tasks)
    task_by_id = {str(task.get("task_id")): task for task in tasks}
    project_id = str(plan.get("project_id", ""))
    branch_ids = sorted({str(task.get("branch_id") or task.get("task_type") or "default_branch") for task in tasks}) or ["default_branch"]
    hierarchy_agents = [
        make_agent(agent_id="program_controller", execution_level="L0", project_id=project_id),
        make_agent(agent_id="project_manager", execution_level="L1", project_id=project_id, reports_to="program_controller"),
        make_agent(agent_id="independent_reviewer", execution_level="L4", project_id=project_id, reports_to="project_manager"),
    ]
    for branch_id in branch_ids:
        hierarchy_agents.append(make_agent(agent_id=f"{branch_id}_manager", execution_level="L2", project_id=project_id, branch_id=branch_id, reports_to="project_manager"))
    for task in tasks:
        branch_id = str(task.get("branch_id") or task.get("task_type") or "default_branch")
        hierarchy_agents.append(
            make_agent(
                agent_id=str(task.get("owner_agent") or f"{task.get('task_id')}_agent"),
                execution_level="L3",
                project_id=project_id,
                branch_id=branch_id,
                task_id=str(task.get("task_id", "")),
                reports_to=f"{branch_id}_manager",
                allowed_files=list(task.get("allowed_files", []) or []),
            )
        )
    hierarchy_contract = {
        "kind": "DynamicTreeHierarchyContract",
        "project_id": project_id,
        "agents": hierarchy_agents,
        "validation": validate_hierarchy(hierarchy_agents),
        "created_at": now(),
    }
    write_json(pathlib.Path(out_dir) / "hierarchy_contract.json", hierarchy_contract)
    if hierarchy_agents:
        l3_sample = next((agent for agent in hierarchy_agents if agent.get("execution_level") == "L3"), None)
        if l3_sample:
            evaluate_authority(
                l3_sample,
                "approve_delivery",
                target={"project_id": project_id},
                ledger_path=pathlib.Path(out_dir) / "hierarchy_events.jsonl",
            )
    candidates = [{"agent_id": str(task.get("owner_agent", "")), "current_load": 0, "critical_path_ready": True} for task in tasks]
    seen_candidates = {item["agent_id"] for item in candidates if item["agent_id"]}
    candidates = [item for item in candidates if item["agent_id"]]

    for task in sorted(tasks, key=lambda item: int(item.get("estimated_completion_order", 0) or 0)):
        task_id = str(task.get("task_id", ""))
        status = statuses.get(task_id, str(task.get("status", "pending")))
        readiness = can_start_task(task, statuses)
        owner = str(task.get("owner_agent", ""))
        recent = [event for event in performance_events if str(event.get("agent_id")) == owner][-5:]
        profile = snapshot.get("agents", {}).get(owner, {}) if isinstance(snapshot.get("agents"), dict) else {}
        intervention = evaluate_intervention(profile, recent)
        replan_reasons: list[str] = []
        if status == "blocked":
            replan_reasons.append("task_blocked")
        if not readiness["can_start"] and task_id in critical_path:
            replan_reasons.append("critical_dependency_wait")
        if int(intervention.get("intervention_level", 0)) >= 2:
            replan_reasons.append("agent_intervention_required")
        if not replan_reasons:
            continue

        local_candidates = list(candidates)
        reviewer = str(task.get("reviewer_agent", ""))
        if reviewer and reviewer not in seen_candidates:
            local_candidates.append({"agent_id": reviewer, "current_load": 0, "critical_path_ready": True})
        assignment = choose_agent_for_task(task, local_candidates, snapshot, health)
        risk_context = risk_context_from_task(
            run_id=str(plan.get("project_id", "")),
            project_id=str(plan.get("project_id", "")),
            task=task,
            health=health,
            performance_snapshot=snapshot,
            budget_remaining=2,
            circuit_state=str((provider_state or {}).get("circuit_state", "closed")),
        )
        risk_decision = dispatch_risk_selected(
            risk_context,
            ledger_path=pathlib.Path(out_dir) / "risk_dispatch_decisions.jsonl",
        )
        if int(intervention.get("intervention_level", 0)) >= 3 and reviewer:
            assignment["selected_agent"] = reviewer
        action_names = list(intervention.get("actions", []))
        if status == "blocked":
            action_names.append("unblock_dependencies")
        if task_id in critical_path:
            action_names.append("protect_critical_path")
        append_task_event(
            out_dir,
            task,
            "replanned",
            status="pending" if status == "blocked" and readiness["can_start"] else status,
            reason=";".join(replan_reasons),
            evidence_refs=["project_health.json", "agent_performance_snapshot.json"],
        )
        decision = record_manager_decision(
            out_dir,
            project_id=str(plan.get("project_id", "")),
            task_id=task_id,
            decision_type="replan",
            candidate_agents=[item["agent_id"] for item in local_candidates],
            selected_agent=str(assignment.get("selected_agent") or owner),
            evidence_used=["project_health.json", "agent_performance_snapshot.json", "task_ledger.jsonl", "risk_dispatch_decisions.jsonl"],
            performance_snapshot=snapshot,
            project_health_snapshot=health,
            reason=";".join(replan_reasons + [f"risk_dispatch:{risk_decision['selected_mode']}"]),
            alternatives_rejected=[item["agent_id"] for item in local_candidates if item["agent_id"] != assignment.get("selected_agent")],
            resulting_scope=action_names,
            resulting_budget={"budget_state": budget_state or {}, "provider_state": provider_state or {}},
            required_review_level=str(assignment.get("required_review_level", "normal_review")),
        )
        actions.append(
            {
                "task_id": task_id,
                "owner_agent": owner,
                "selected_agent": decision["selected_agent"],
                "reasons": replan_reasons,
                "actions": action_names,
                "risk_dispatch_decision_id": risk_decision["decision_id"],
                "risk_selected_challengers": risk_decision["selected_challengers"],
            }
        )

    result = {
        "kind": "ProjectManagerCycle",
        "project_id": str(plan.get("project_id", "")),
        "critical_path": critical_path,
        "health": health,
        "actions": actions,
        "action_count": len(actions),
        "created_at": now(),
    }
    write_json(pathlib.Path(out_dir) / "project_manager_cycle_latest.json", result)
    return result
