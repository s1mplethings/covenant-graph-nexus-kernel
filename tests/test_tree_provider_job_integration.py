from __future__ import annotations

from scripts import decomposition_tree, post_build_repair, provider_jobs, repair_acceptance


def sample_tree() -> dict:
    return decomposition_tree.build_case03_tree(
        user_goal="Build a local board",
        project_plan={"expected_project_structure": ["app/main.py"]},
        component_pipeline={"components": [{"id": "backend", "required_paths": ["app/main.py"]}]},
    )


def test_provider_job_requires_tree_node_id() -> None:
    action = {
        "id": "backend.leaf.001",
        "goal": "repair root",
        "owns": ["app/main.py"],
        "issue_id": "ROOT-404",
        "expected_behavior": "GET / returns 200",
        "observed_behavior": "GET / returns 404",
        "evidence": ["http probe"],
        "target_files": ["app/main.py"],
        "current_source": "def app(): pass",
        "affected_behavior_probe": ["http_root_probe"],
    }
    assert any("tree_node_id" in item for item in provider_jobs.validate_repair_job_contract(action))
    action["tree_node_id"] = "capability.static_web_entry"
    assert provider_jobs.validate_repair_job_contract(action) == []


def test_case01_static_root_issue_creates_exact_provider_job(tmp_path) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "app").mkdir(parents=True)
    (candidate / "app" / "main.py").write_text("def app():\n    return 404\n", encoding="utf-8")
    tree, issues = decomposition_tree.bind_issues_to_tree(
        sample_tree(),
        [{
            "issue_id": "ROOT-404",
            "failed_requirement": "static root",
            "expected_behavior": "GET / returns 200",
            "observed_behavior": "GET / returns 404",
            "affected_files": ["app/main.py"],
            "affected_provider_job": "backend.leaf.001",
            "repair_route": "provider",
            "repairable": True,
            "external_evidence": [{"authority": "http_root_probe"}],
            "root_cause_key": "static-root-404",
        }],
    )
    clustered = post_build_repair.cluster_issue_root_causes(
        {"issues": issues},
        {"components": [{"id": "backend", "leaf_work_graph": {"leaves": [{"leaf_id": "backend.leaf.001", "owns": ["app/main.py"]}]}}]},
    )
    plan = post_build_repair.bind_repair_plan_to_issue_ledger(
        {}, clustered,
        {"components": [{"id": "backend", "leaf_work_graph": {"leaves": [{"leaf_id": "backend.leaf.001", "owns": ["app/main.py"]}]}}]},
        candidate_dir=candidate,
        decomposition_tree_doc=tree,
    )
    assert plan["tree_contract_required"] is True
    assert len(plan["provider_actions"]) == 1
    action = plan["provider_actions"][0]
    assert action["path"] == "app/main.py"
    assert action["tree_node_id"] == "capability.static_web_entry"
    for field in ("issue_id", "expected_behavior", "observed_behavior", "evidence", "target_files", "current_source", "affected_behavior_probe"):
        assert action[field]


def test_repair_acceptance_updates_tree_node_evidence() -> None:
    result = repair_acceptance.assess_provider_job_partial_acceptance(
        target_file="app/main.py",
        before_content="value = b'x'.decode('UTF8-SIG')\n",
        after_content="value = b'x'.decode('utf-8-sig')\n",
        coherence_before=[{"kind": "invalid_python_codec", "path": "app/main.py", "expected_behavior": "registered codec", "observed_behavior": "UTF8-SIG"}],
        coherence_after=[],
        evidence_facts=[],
        owned_paths={"app/main.py"},
        syntax_safe=True,
        tree_node_id="semantic_contract.main_entry",
    )
    assert result["safe_to_accept_partial"] is True
    assert result["evidence_tree_updates"][0]["tree_node_id"] == "semantic_contract.main_entry"
    updated = decomposition_tree.apply_evidence_updates(sample_tree(), result["evidence_tree_updates"])
    node = next(item for item in updated["nodes"] if item["node_id"] == "semantic_contract.main_entry")
    assert node["status"] == "pass"
    assert node["current_evidence"]
    assert result.get("case_score_required_for_acceptance", False) is False


def test_target_issue_improvement_required_for_tree_node_acceptance() -> None:
    result = repair_acceptance.assess_provider_job_partial_acceptance(
        target_file="app/main.py",
        before_content="def app(): return 404\n",
        after_content="def app():\n    return 404\n",
        coherence_before=[{"kind": "static_root_404", "path": "app/main.py", "expected_behavior": "GET / returns 200"}],
        coherence_after=[{"kind": "static_root_404", "path": "app/main.py", "expected_behavior": "GET / returns 200"}],
        evidence_facts=[],
        owned_paths={"app/main.py"},
        syntax_safe=True,
        tree_node_id="capability.static_web_entry",
    )
    assert result["safe_to_accept_partial"] is False
    assert result["reason"] == "NO_TARGET_ISSUE_IMPROVEMENT"
    assert result["evidence_tree_updates"] == []


def test_case_score_not_required_for_tree_node_acceptance() -> None:
    result = repair_acceptance.assess_provider_job_partial_acceptance(
        target_file="app/main.py",
        before_content="value = b'x'.decode('UTF8-SIG')\n",
        after_content="value = b'x'.decode('utf-8-sig')\n",
        coherence_before=[{"kind": "invalid_python_codec", "path": "app/main.py", "expected_behavior": "registered codec"}],
        coherence_after=[],
        evidence_facts=[],
        owned_paths={"app/main.py"},
        syntax_safe=True,
        tree_node_id="semantic_contract.main_entry",
    )
    assert result["safe_to_accept_partial"] is True
    assert result.get("case_score_required_for_acceptance", False) is False
