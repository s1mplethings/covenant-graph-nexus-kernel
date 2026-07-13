from __future__ import annotations

import json
import pathlib

from scripts.agent_growth_budget import default_growth_budget
from scripts.agent_growth_orchestrator import controlled_leaf_build, run_controlled_dynamic_growth
from scripts.agent_growth_planner import plan_dynamic_growth
from scripts.agent_project_management import build_performance_snapshot, choose_agent_for_task, record_performance_event
from scripts.agent_scope_contract import load_scope_contract
from scripts.agent_tree_contracts import read_json, read_jsonl, write_json
from scripts.agent_tree_registry import agent_by_id
from scripts.agent_tree_shared_context import create_shared_context
from scripts import provider_transport


GOAL = "做一个本地 AI 知识工作台，用于导入资料、检索、任务化跟踪、生成报告，并支持本地模型适配层和界面"


def test_controlled_dynamic_tree_writes_and_consumes_management_ledgers(tmp_path: pathlib.Path) -> None:
    result = run_controlled_dynamic_growth(goal=GOAL, project_name="Local AI Knowledge Studio", out_dir=tmp_path)
    assert result["verdict"] == "PASS"
    assert read_json(tmp_path / "project_plan.json", {})["critical_path"]
    task_events = read_jsonl(tmp_path / "task_ledger.jsonl")
    perf_events = read_jsonl(tmp_path / "agent_performance_ledger.jsonl")
    decisions = read_jsonl(tmp_path / "project_manager_decisions.jsonl")
    assert any(event["event_type"] == "checkpoint" for event in task_events)
    assert any(event["event_type"] == "task_completed" for event in perf_events)
    assert any(decision["decision_type"] == "spawn" for decision in decisions)
    assert any(decision["decision_type"] == "promote" for decision in decisions)


def test_successful_agent_gets_preferred_for_similar_task_authorization(tmp_path: pathlib.Path) -> None:
    record_performance_event(tmp_path, agent_id="leaf_good", task_id="backend_1", task_type="backend", event_type="task_completed", first_pass=True)
    record_performance_event(tmp_path, agent_id="leaf_good", task_id="backend_2", task_type="backend", event_type="task_completed", first_pass=True)
    record_performance_event(tmp_path, agent_id="leaf_bad", task_id="backend_3", task_type="backend", event_type="task_failed")
    snapshot = build_performance_snapshot(tmp_path)
    decision = choose_agent_for_task(
        {"project_id": "p", "task_id": "backend_4", "task_type": "backend", "priority": "normal", "dependency_task_ids": []},
        [{"agent_id": "leaf_good"}, {"agent_id": "leaf_bad"}],
        snapshot,
    )
    assert decision["selected_agent"] == "leaf_good"
    assert "backend" in snapshot["agents"]["leaf_good"]["preferred_task_types"]


def test_scope_violation_shrinks_authority_and_forces_reviewer(tmp_path: pathlib.Path) -> None:
    shared = create_shared_context("Local AI Knowledge Studio", GOAL)
    registry = plan_dynamic_growth(shared, tmp_path)
    project = tmp_path / "project"
    cp = controlled_leaf_build(
        agent_by_id(registry, "search_service_leaf"),
        project_dir=project,
        out_dir=tmp_path,
        budget=default_growth_budget(),
        injected_files=["README.md"],
    )
    contract = load_scope_contract(tmp_path, "search_service_leaf")
    perf = read_jsonl(tmp_path / "agent_performance_ledger.jsonl")
    assert cp["verdict"] == "FAIL"
    assert contract["intervention_level"] == 2
    assert contract["required_reviewer"] == "backend_branch_agent"
    assert any(event["event_type"] == "scope_violation" for event in perf)


def test_provider_quota_blocks_without_agent_score_penalty_and_circuit_prevents_duplicate_charge(tmp_path: pathlib.Path) -> None:
    calls = {"count": 0}

    def quota(endpoint, payload, token, timeout):
        calls["count"] += 1
        return None, "HTTP 403: Key usage limit exceeded [retryable=false]"

    first = provider_transport.governed_post_json_with_retry(
        "https://example.test/v1/responses",
        {"model": "gpt-5.4-nano", "messages": [{"role": "user", "content": "x"}], "max_tokens": 10},
        "fake-provider-token",
        1,
        run_dir=tmp_path,
        project_id="p",
        task_id="task_leaf",
        agent_id="leaf",
        request_type="leaf_generation",
        model="gpt-5.4-nano",
        endpoint_method="responses",
        api_budget="standard",
        post_once_fn=quota,
        sleep_fn=lambda _: None,
        jitter_fn=lambda: 0,
    )
    record_performance_event(tmp_path, agent_id="leaf", task_id="task_leaf", task_type="backend", event_type="provider_quota", external_blocker="provider_quota")
    trust = build_performance_snapshot(tmp_path)["agents"]["leaf"]["trust_score"]
    second = provider_transport.governed_post_json_with_retry(
        "https://example.test/v1/responses",
        {"model": "gpt-5.4-nano", "messages": [{"role": "user", "content": "x"}], "max_tokens": 10},
        "fake-provider-token",
        1,
        run_dir=tmp_path,
        project_id="p",
        task_id="task_leaf",
        agent_id="leaf",
        request_type="leaf_generation",
        model="gpt-5.4-nano",
        endpoint_method="responses",
        api_budget="standard",
        post_once_fn=quota,
    )
    assert first.error_type == "PROVIDER_KEY_USAGE_LIMIT"
    assert second.error == "BLOCKED_PROVIDER_CIRCUIT_OPEN"
    assert calls["count"] == 1
    assert trust == 0.72


def test_parent_oversized_split_records_management_responsibility_and_smaller_feedback(tmp_path: pathlib.Path) -> None:
    shared = create_shared_context("Local AI Knowledge Studio", GOAL)
    registry = plan_dynamic_growth(shared, tmp_path)
    contract = load_scope_contract(tmp_path, "search_service_leaf")
    contract["allowed_files"] = [f"app/services/oversized_{index}.py" for index in range(default_growth_budget()["max_leaf_expected_files"] + 1)]
    write_json(tmp_path / "scope_contracts" / "search_service_leaf.json", contract)
    cp = controlled_leaf_build(agent_by_id(registry, "search_service_leaf"), project_dir=tmp_path / "project", out_dir=tmp_path, budget=default_growth_budget())
    perf = read_jsonl(tmp_path / "agent_performance_ledger.jsonl")
    feedback = read_jsonl(tmp_path / "feedback_tasks.jsonl")
    assert cp["verdict"] == "NEEDS_SPLIT"
    assert any(event["agent_id"] == "backend_branch_agent" and event["event_type"] == "oversized_scope" for event in perf)
    assert any("spawn_smaller_children" in event.get("allowed_actions", []) for event in feedback)
