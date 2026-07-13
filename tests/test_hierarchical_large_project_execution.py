from __future__ import annotations

import json
import pathlib

from scripts.hierarchical_execution import (
    AUTHORITIES,
    HierarchicalScheduler,
    build_scale_project,
    compare_context_costs,
    detect_under_sized_fragmentation,
    evaluate_authority,
    grant_temporary_authorization,
    make_agent,
    make_context_packet,
    new_ownership_registry,
    oversized_gate,
    prepare_registry_for_project,
    run_fault_injections,
    run_scale_simulation,
    split_oversized_task,
    validate_context_packet,
    validate_hierarchy,
)


def test_agent_contract_has_required_fields() -> None:
    agent = make_agent(agent_id="leaf", execution_level="L3", project_id="p", reports_to="branch_manager")
    required = {
        "agent_id",
        "agent_type",
        "execution_level",
        "reports_to",
        "managed_agents",
        "project_id",
        "branch_id",
        "task_id",
        "authority",
        "prohibited_actions",
        "scope",
        "allowed_files",
        "forbidden_files",
        "file_ownership",
        "context_budget",
        "output_budget",
        "api_budget",
        "concurrency_limit",
        "escalation_target",
        "acceptance_responsibility",
        "performance_policy",
        "status",
        "heartbeat_at",
        "lease_expires_at",
        "created_at",
        "updated_at",
    }
    assert required.issubset(agent)
    assert set(agent["authority"]).issubset(AUTHORITIES)


def test_valid_hierarchy_relationships() -> None:
    agents = [
        make_agent(agent_id="program", execution_level="L0", project_id="p"),
        make_agent(agent_id="pm", execution_level="L1", project_id="p", reports_to="program"),
        make_agent(agent_id="bm", execution_level="L2", project_id="p", reports_to="pm"),
        make_agent(agent_id="leaf", execution_level="L3", project_id="p", reports_to="bm"),
        make_agent(agent_id="reviewer", execution_level="L4", project_id="p", reports_to="pm"),
    ]
    assert validate_hierarchy(agents)["valid"] is True


def test_invalid_cross_level_relationship_is_rejected() -> None:
    agents = [
        make_agent(agent_id="program", execution_level="L0", project_id="p"),
        make_agent(agent_id="leaf", execution_level="L3", project_id="p", reports_to="program"),
    ]
    result = validate_hierarchy(agents)
    assert result["valid"] is False
    assert result["violations"]


def test_l3_cannot_approve_project_delivery(tmp_path: pathlib.Path) -> None:
    leaf = make_agent(agent_id="leaf", execution_level="L3", project_id="p", reports_to="bm")
    result = evaluate_authority(leaf, "approve_delivery", ledger_path=tmp_path / "events.jsonl")
    assert result["status"] == "rejected"
    assert (tmp_path / "events.jsonl").exists()


def test_l4_cannot_create_code_repair() -> None:
    reviewer = make_agent(agent_id="reviewer", execution_level="L4", project_id="p", reports_to="pm")
    assert evaluate_authority(reviewer, "create_repair_task")["status"] == "rejected"


def test_l2_cannot_change_other_branch_ownership() -> None:
    branch_manager = make_agent(agent_id="bm_a", execution_level="L2", project_id="p", branch_id="a", reports_to="pm")
    result = evaluate_authority(branch_manager, "change_file_owner", target={"branch_id": "b", "file": "src/b.py"})
    assert result["status"] == "rejected"
    assert result["reason"] == "cross_branch_owner_change_denied"


def test_l1_leaf_scope_escalates_through_l2() -> None:
    pm = make_agent(agent_id="pm", execution_level="L1", project_id="p", reports_to="program")
    result = evaluate_authority(pm, "change_scope", target={"leaf_task": True, "oversized_scope": True})
    assert result["status"] == "escalation_required"


def test_temporary_authorization_allows_and_expiry_blocks(tmp_path: pathlib.Path) -> None:
    program = make_agent(agent_id="program", execution_level="L0", project_id="p")
    leaf = make_agent(agent_id="leaf", execution_level="L3", project_id="p", reports_to="bm", branch_id="a")
    auth = grant_temporary_authorization(granted_by=program, granted_to=leaf, authority="change_scope", reason="incident", scope={"branch_id": "a"}, ttl_seconds=60, ledger_path=tmp_path / "events.jsonl")
    allowed = evaluate_authority(leaf, "change_scope", target={"branch_id": "a"}, temporary_authorizations=[auth])
    assert allowed["status"] == "allowed_by_temporary_authorization"
    expired = dict(auth)
    expired["expires_at"] = "2000-01-01T00:00:00+00:00"
    denied = evaluate_authority(leaf, "change_scope", target={"branch_id": "a"}, temporary_authorizations=[expired])
    assert denied["status"] in {"rejected", "escalation_required"}


def test_context_packet_preserves_invariants_over_budget() -> None:
    payload = {
        "frozen_requirements": ["must import", "must export"],
        "forbidden_scope": ["cloud upload"],
        "acceptance_criteria": ["startup", "restart"],
        "current_task": "implement import",
        "dependencies": ["schema"],
        "interface_contract": {"api": "v1"},
        "confirmed_findings": [{"id": "f1"}],
        "ownership": {"src/a.py": "branch_a"},
        "unresolved_questions": ["encoding edge"],
        "irrelevant_logs": ["x" * 2000],
    }
    packet = make_context_packet(source_level="L2", target_level="L3", project_id="p", task_id="t", payload=payload, budget=80)
    validation = validate_context_packet(packet, payload)
    assert validation["valid"] is True
    assert packet["unresolved_questions"] == ["encoding edge"]
    assert packet["packet_id"] == make_context_packet(source_level="L2", target_level="L3", project_id="p", task_id="t", payload=payload, budget=80)["packet_id"]


def test_l3_l2_l1_reporting_packet_fields() -> None:
    payload = {"current_task": "leaf done", "evidence_refs": ["e.json"], "dependencies": ["d"], "frozen_requirements": ["m"], "forbidden_scope": ["x"], "interface_contract": {"v": 1}, "ownership": {"a": "b"}}
    packet = make_context_packet(source_level="L3", target_level="L2", project_id="p", task_id="t", payload=payload, budget=500)
    assert {"packet_id", "source_level", "target_level", "summary", "evidence_refs", "source_hashes"}.issubset(packet)
    packet2 = make_context_packet(source_level="L2", target_level="L1", project_id="p", task_id="b", payload=payload, budget=500)
    packet3 = make_context_packet(source_level="L1", target_level="L0", project_id="p", task_id="p", payload=payload, budget=500)
    assert packet2["source_level"] == "L2"
    assert packet3["target_level"] == "L0"


def test_oversized_task_is_split_and_parent_records_management() -> None:
    task = {"task_id": "big", "branch_id": "core", "files": [f"f{i}.py" for i in range(7)], "components": ["a", "b", "c"], "phases": ["design", "implementation", "test"]}
    gate = oversized_gate(task)
    assert gate["split_required"] is True
    split = split_oversized_task(task, branch_manager_id="core_manager")
    assert split["parent"]["status"] == "coordination"
    assert len(split["children"]) >= 3
    assert all(child["parent_task_id"] == "big_coordination" for child in split["children"])


def test_under_sized_fragmentation_detects_repeated_file() -> None:
    tasks = [{"task_id": f"t{i}", "files": ["same.py"], "acceptance": "ok"} for i in range(5)]
    assert detect_under_sized_fragmentation(tasks)["fragmented"] is True


def test_ownership_registry_duplicate_missing_and_interface_approval() -> None:
    registry = new_ownership_registry("p")
    assert registry.register_file("src/a.py", "a")["status"] == "registered"
    assert registry.register_file("src/a.py", "b")["reason"] == "duplicate_owner"
    proposal = registry.propose_interface_change("api.users", producer="a", consumers=["b", "c"], version="2.0", schema={"fields": ["id"]}, breaking=True)
    for branch in ["a", "b", "c"]:
        proposal = registry.approve_interface_change(proposal, branch)
    assert proposal["status"] == "approved"
    merge = registry.validate_merge([{"task_id": "t", "branch_id": "b", "files": ["src/a.py"]}])
    assert merge["valid"] is False


def test_scheduler_completes_without_dependency_or_duplicate_violations(tmp_path: pathlib.Path) -> None:
    project = build_scale_project(project_id="p", branch_count=3, task_count=15, agent_count=8)
    registry = prepare_registry_for_project(project)
    scheduler = HierarchicalScheduler(project=project, registry=registry, out_dir=tmp_path, project_concurrency=4, branch_concurrency=2)
    result = scheduler.run_to_completion()
    assert result["status"] == "PASS"
    assert result["completed"] == 15
    assert result["dependency_violations"] == 0
    assert result["duplicate_execution"] == 0
    assert result["ownership_conflicts"] == 0


def test_checkpoint_restore_and_stale_lease_recovery(tmp_path: pathlib.Path) -> None:
    project = build_scale_project(project_id="p", branch_count=2, task_count=6, agent_count=6)
    registry = prepare_registry_for_project(project)
    scheduler = HierarchicalScheduler(project=project, registry=registry, out_dir=tmp_path, lease_seconds=1)
    scheduler.schedule_once()
    for lease in scheduler.leases.values():
        lease["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
    recovered = scheduler.recover_stale_leases()
    checkpoint = scheduler.checkpoint("after_recovery")
    restored = scheduler.restore_checkpoint(checkpoint)
    assert recovered["count"] > 0
    assert restored["data_loss"] is False
    assert pathlib.Path(tmp_path / "checkpoints" / "after_recovery.json").exists()


def test_duplicate_reward_prevention(tmp_path: pathlib.Path) -> None:
    project = build_scale_project(project_id="p", branch_count=1, task_count=1, agent_count=4)
    registry = prepare_registry_for_project(project)
    scheduler = HierarchicalScheduler(project=project, registry=registry, out_dir=tmp_path)
    scheduler.schedule_once()
    scheduler.complete_task("task_0000")
    scheduler.complete_task("task_0000")
    assert scheduler.metrics["agent_score_corruption"] == 1


def test_scale_simulation_s_and_m_pass(tmp_path: pathlib.Path) -> None:
    s = run_scale_simulation(tmp_path, label="S", branch_count=3, task_count=15, agent_count=5)
    m = run_scale_simulation(tmp_path, label="M", branch_count=8, task_count=75, agent_count=15)
    assert s["status"] == "PASS"
    assert m["status"] == "PASS"
    assert m["duplicate_execution"] == 0


def test_fault_injection_matrix_has_required_25_cases(tmp_path: pathlib.Path) -> None:
    rows = run_fault_injections(tmp_path)
    assert len(rows) == 25
    assert all(row["final_status"] == "PASS" for row in rows)
    assert any(row["injection"] == "malicious_irrelevant_llm_finding" and row["agent_score_impact"] == "no_penalty" for row in rows)


def test_context_cost_comparison_proves_compression() -> None:
    payload = {
        "frozen_requirements": ["startup", "export"],
        "forbidden_scope": ["cloud"],
        "acceptance_criteria": ["health"],
        "current_task": "task",
        "dependencies": ["dep"],
        "interface_contract": {"v": 1},
        "confirmed_findings": [{"id": "f"}],
        "ownership": {"a": "b"},
        "logs": ["x" * 5000],
    }
    comparison = compare_context_costs(payload, task_count=50)
    assert comparison["context_token_savings_vs_uncompressed"] > 0
    assert comparison["must_have_retention"] == 1.0
    assert comparison["hierarchical_risk_selected"]["provider_calls"] < comparison["hierarchical_without_context_compression"]["provider_calls"]


def test_telegram_mainline_does_not_import_hierarchy_or_risk_dispatcher() -> None:
    text = pathlib.Path("scripts/telegram_live_bridge.py").read_text(encoding="utf-8")
    assert "hierarchical_execution" not in text
    assert "run_hierarchical_large_project_execution" not in text
    assert "risk_dispatcher" not in text


def test_json_serializable_scale_project() -> None:
    project = build_scale_project(project_id="p", branch_count=3, task_count=15, agent_count=5)
    json.dumps(project, ensure_ascii=False)
