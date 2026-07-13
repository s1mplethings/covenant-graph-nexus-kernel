from __future__ import annotations

import pathlib

from scripts.agent_project_management import (
    append_task_event,
    build_performance_snapshot,
    build_project_plan,
    can_start_task,
    choose_agent_for_task,
    evaluate_intervention,
    initialize_task_ledger,
    parent_management_responsibility,
    record_performance_event,
    reward_authorization,
    run_project_manager_cycle,
    task_statuses_from_ledger,
)
from scripts.agent_tree_contracts import read_jsonl


def _task(task_type: str = "backend", risk: str = "normal") -> dict:
    return {
        "project_id": "p1",
        "task_id": "task_backend",
        "task_type": task_type,
        "priority": "normal",
        "reviewer_agent": "reviewer",
        "risk_level": risk,
        "dependency_task_ids": [],
    }


def test_high_quality_history_agent_wins_deterministically(tmp_path: pathlib.Path) -> None:
    record_performance_event(tmp_path, agent_id="agent_good", task_id="t1", task_type="backend", event_type="task_completed", first_pass=True)
    record_performance_event(tmp_path, agent_id="agent_good", task_id="t2", task_type="backend", event_type="task_completed", first_pass=True)
    record_performance_event(tmp_path, agent_id="agent_bad", task_id="t3", task_type="backend", event_type="scope_violation", scope_violations=1)
    snapshot = build_performance_snapshot(tmp_path)
    candidates = [{"agent_id": "agent_bad"}, {"agent_id": "agent_good"}]
    first = choose_agent_for_task(_task(), candidates, snapshot)
    second = choose_agent_for_task(_task(), candidates, snapshot)
    assert first["selected_agent"] == "agent_good"
    assert first == second


def test_high_score_overloaded_agent_can_lose(tmp_path: pathlib.Path) -> None:
    record_performance_event(tmp_path, agent_id="agent_good", task_id="t1", task_type="backend", event_type="task_completed", first_pass=True)
    record_performance_event(tmp_path, agent_id="agent_good", task_id="t2", task_type="backend", event_type="task_completed", first_pass=True)
    snapshot = build_performance_snapshot(tmp_path)
    snapshot["agents"]["agent_good"]["current_load"] = 4
    snapshot["agents"]["agent_free"] = {"agent_id": "agent_free", "quality_score": 0.74, "first_pass_score": 0.74, "scope_discipline_score": 0.74, "delivery_predictability_score": 0.74, "collaboration_score": 0.74, "recovery_score": 0.74, "risk_management_score": 0.74, "trust_score": 0.74}
    result = choose_agent_for_task(_task(), [{"agent_id": "agent_good"}, {"agent_id": "agent_free"}], snapshot)
    assert result["selected_agent"] == "agent_free"


def test_provider_blocker_does_not_lower_agent_score(tmp_path: pathlib.Path) -> None:
    before = build_performance_snapshot(tmp_path)
    record_performance_event(tmp_path, agent_id="agent_a", task_id="t1", task_type="backend", event_type="provider_quota", external_blocker="provider_quota")
    after = build_performance_snapshot(tmp_path)
    assert after["agents"]["agent_a"]["trust_score"] == before.get("agents", {}).get("agent_a", {}).get("trust_score", 0.72)


def test_scope_violation_and_false_success_trigger_intervention(tmp_path: pathlib.Path) -> None:
    ev1 = record_performance_event(tmp_path, agent_id="agent_a", task_id="t1", task_type="backend", event_type="scope_violation", scope_violations=1)
    ev2 = record_performance_event(tmp_path, agent_id="agent_a", task_id="t2", task_type="backend", event_type="false_success", false_success_attempt=True)
    snapshot = build_performance_snapshot(tmp_path)
    assert snapshot["agents"]["agent_a"]["trust_score"] < 0.72
    intervention = evaluate_intervention(snapshot["agents"]["agent_a"], [ev1, ev2])
    assert intervention["intervention_level"] >= 3
    assert "split_or_reassign" in intervention["actions"] or "replace_owner" in intervention["actions"]


def test_single_failure_does_not_prune_but_repeated_controllable_failures_can(tmp_path: pathlib.Path) -> None:
    first = record_performance_event(tmp_path, agent_id="agent_a", task_id="t1", task_type="backend", event_type="task_failed")
    assert evaluate_intervention({}, [first])["intervention_level"] == 1
    events = [record_performance_event(tmp_path, agent_id="agent_a", task_id=f"t{i}", task_type="backend", event_type="task_failed") for i in range(2, 6)]
    assert evaluate_intervention({}, [first] + events)["intervention_level"] == 5


def test_parent_bad_split_lowers_management_score(tmp_path: pathlib.Path) -> None:
    event = parent_management_responsibility(parent_agent="branch", child_task={"task_id": "leaf_task"}, failure_reason="oversized_scope", out_dir=tmp_path)
    snapshot = build_performance_snapshot(tmp_path)
    assert event["management_responsibility"] is True
    assert snapshot["agents"]["branch"]["management_score"] < 0.72


def test_dependencies_block_task_until_completed(tmp_path: pathlib.Path) -> None:
    task = {"task_id": "task_b", "dependency_task_ids": ["task_a"]}
    assert can_start_task(task, {})["can_start"] is False
    assert can_start_task(task, {"task_a": "completed"})["can_start"] is True


def test_project_plan_critical_path_and_reward_authorization(tmp_path: pathlib.Path) -> None:
    plan = build_project_plan(project_id="p1", frozen_goal="local AI 工作台 with UI", required_outputs=["app/main.py"], project_budget={})
    assert "task_delivery" in plan["critical_path"]
    initialize_task_ledger(tmp_path, plan["work_breakdown_structure"])
    append_task_event(tmp_path, plan["work_breakdown_structure"][0], "checkpoint", status="completed")
    assert task_statuses_from_ledger(tmp_path)[plan["work_breakdown_structure"][0]["task_id"]] == "completed"
    record_performance_event(tmp_path, agent_id="agent_a", task_id="t1", task_type="backend", event_type="task_completed", first_pass=True)
    record_performance_event(tmp_path, agent_id="agent_a", task_id="t2", task_type="backend", event_type="task_completed", first_pass=True)
    profile = build_performance_snapshot(tmp_path)["agents"]["agent_a"]
    assert "preferred_for_similar_tasks" in reward_authorization(profile, "backend")["actions"]


def test_project_manager_cycle_replans_blocked_critical_task_and_records_history(tmp_path: pathlib.Path) -> None:
    plan = build_project_plan(
        project_id="knowledge",
        frozen_goal="本地 AI 知识工作台 导入资料 知识库 检索 报告",
        acceptance_contract={},
        required_outputs=["app/services/search_service.py", "tests/"],
        project_budget={},
    )
    from scripts.agent_project_management import save_project_plan

    save_project_plan(tmp_path, plan)
    initialize_task_ledger(tmp_path, plan["work_breakdown_structure"])
    by_id = {task["task_id"]: task for task in plan["work_breakdown_structure"]}
    for task_id in ("task_requirements", "task_architecture", "task_backend", "task_document_import"):
        append_task_event(tmp_path, by_id[task_id], "checkpoint", status="completed", reason="test_ready")
    append_task_event(tmp_path, by_id["task_knowledge_search"], "checkpoint", status="blocked", reason="external_review_wait")
    record_performance_event(
        tmp_path,
        agent_id="search_service_leaf",
        task_id="task_knowledge_search",
        task_type="knowledge_search",
        event_type="scope_violation",
        scope_violations=1,
    )

    result = run_project_manager_cycle(tmp_path, provider_state={"circuit_state": "closed"})
    decisions = read_jsonl(tmp_path / "project_manager_decisions.jsonl")
    history = read_jsonl(tmp_path / "project_health_history.jsonl")
    statuses = task_statuses_from_ledger(tmp_path)

    assert result["action_count"] >= 1
    assert any(action["task_id"] == "task_knowledge_search" and "protect_critical_path" in action["actions"] for action in result["actions"])
    assert any(decision["decision_type"] == "replan" and decision["task_id"] == "task_knowledge_search" for decision in decisions)
    assert history and history[-1]["blocked_count"] >= 1
    assert statuses["task_knowledge_search"] == "pending"


def test_high_risk_task_requires_independent_reviewer(tmp_path: pathlib.Path) -> None:
    snapshot = {"agents": {"agent_a": {"agent_id": "agent_a", "quality_score": 0.9, "first_pass_score": 0.9, "scope_discipline_score": 0.9, "delivery_predictability_score": 0.9, "collaboration_score": 0.9, "risk_management_score": 0.9, "trust_score": 0.9}}}
    task = _task(risk="high")
    task["reviewer_agent"] = "agent_a"
    result = choose_agent_for_task(task, [{"agent_id": "agent_a"}, {"agent_id": "agent_b"}], snapshot)
    assert result["required_review_level"] == "senior_review"
