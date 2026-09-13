from __future__ import annotations

from scripts import decomposition_tree, issue_ledger


def tree() -> dict:
    return decomposition_tree.build_case03_tree(
        user_goal="Build a local board",
        project_plan={"expected_project_structure": ["app/main.py", "frontend/index.html", "frontend/app.js", "tests/test_board.py"]},
        component_pipeline={
            "components": [
                {"id": "backend", "required_paths": ["app/main.py"]},
                {"id": "frontend", "required_paths": ["frontend/index.html", "frontend/app.js"]},
                {"id": "tests", "required_paths": ["tests/test_board.py"]},
            ]
        },
    )


def test_case01_static_root_failure_maps_to_tree_node() -> None:
    updated, issues = decomposition_tree.bind_issues_to_tree(
        tree(),
        [{
            "issue_id": "ROOT-404",
            "requirement": "static root startup",
            "observed_behavior": "GET / returned HTTP 404",
            "affected_files": ["app/main.py"],
            "affected_provider_job": "backend.leaf.001",
            "repair_route": "provider",
            "repairable": True,
        }],
    )
    assert issues[0]["tree_node_id"] == "capability.static_web_entry"
    node = next(item for item in updated["nodes"] if item["node_id"] == "capability.static_web_entry")
    assert node["status"] == "repairable_fail"
    assert node["mapped_issues"] == ["ROOT-404"]


def test_semantic_failures_map_to_exact_contract_nodes() -> None:
    _, issues = decomposition_tree.bind_issues_to_tree(
        tree(),
        [
            {"issue_id": "MAIN", "symptom": "missing expected symbols: main", "affected_files": ["app/main.py"], "repairable": True},
            {"issue_id": "VERIFY", "symptom": "Selenium forbidden import in canonical verifier", "affected_files": ["tests/test_board.py"], "repairable": True},
        ],
    )
    assert [item["tree_node_id"] for item in issues] == [
        "semantic_contract.main_entry",
        "test_contract.canonical_verifier",
    ]


def test_case03_missing_main_maps_to_semantic_tree_node() -> None:
    _, issues = decomposition_tree.bind_issues_to_tree(
        tree(),
        [{"issue_id": "MAIN", "symptom": "missing expected symbol main", "affected_files": ["app/main.py"], "repairable": True}],
    )
    assert issues[0]["tree_node_id"] == "semantic_contract.main_entry"


def test_case03_selenium_violation_maps_to_test_contract_node() -> None:
    _, issues = decomposition_tree.bind_issues_to_tree(
        tree(),
        [{"issue_id": "SELENIUM", "symptom": "Selenium import violation", "affected_files": ["tests/test_board.py"], "repairable": True}],
    )
    assert issues[0]["tree_node_id"] == "test_contract.canonical_verifier"


def test_unmapped_failure_cannot_create_generic_provider_job() -> None:
    _, issues = decomposition_tree.bind_issues_to_tree(
        tree(),
        [{"issue_id": "UNKNOWN", "symptom": "unrelated opaque failure", "repairable": True}],
    )
    assert issues[0]["tree_node_id"] == ""
    assert issues[0]["issue_type"] == "unmapped_failure"
    assert issues[0]["repairable"] is False
    assert issues[0]["repair_route"] == "halt"


def test_issue_ledger_accepts_tree_mapping() -> None:
    ownership = {"app/main.py": "backend.leaf.001"}
    issues = issue_ledger.issues_from_evaluator_failure(
        {
            "criterion_id": "startup",
            "status": "FAIL",
            "expected_behavior": "Static root starts",
            "observed_behavior": "HTTP 404 from static root",
            "affected_files": ["app/main.py"],
        },
        ownership,
        tree(),
    )
    assert issues[0]["tree_node_id"] == "capability.static_web_entry"


def test_static_root_tree_node_rebinds_wrong_symptom_path_to_entry_owner() -> None:
    issue = {
        "tree_node_id": "capability.static_web_entry",
        "affected_files": ["tests/test_board.py"],
        "affected_provider_job": "tests.leaf.001",
        "repair_route": "provider",
        "repairable": True,
        "evidence": {"paths": ["tests/test_board.py"]},
    }
    rebound = issue_ledger.bind_issue_to_tree_ownership(
        issue,
        tree(),
        {
            "app/main.py": "backend.leaf.001",
            "frontend/index.html": "frontend.leaf.001",
            "tests/test_board.py": "tests.leaf.001",
        },
    )
    assert rebound["affected_files"] == ["app/main.py"]
    assert rebound["affected_provider_job"] == "backend.leaf.001"
