from __future__ import annotations

import pathlib

from scripts.agent_tree_contracts import write_json
from scripts.agent_tree_registry import add_agent, initial_registry, mark_agent_pruned
from scripts.full_dynamic_project_resume_merge import merge_resume_branch
from scripts.run_full_dynamic_real_project_eval import _integration_files


def test_resume_merge_uses_replacement_and_excludes_original(tmp_path: pathlib.Path) -> None:
    registry = initial_registry()
    add_agent(registry, {"action_id": "S1", "parent_agent": "main_agent", "new_agent_id": "test_branch_agent", "role": "TestBranch", "depth": 1, "scope": []})
    add_agent(registry, {"action_id": "S2", "parent_agent": "test_branch_agent", "new_agent_id": "smoke_leaf", "role": "SmokeLeaf", "depth": 2, "scope": []})
    add_agent(registry, {"action_id": "S3", "parent_agent": "test_branch_agent", "new_agent_id": "smoke_leaf_v2", "role": "SmokeLeaf", "depth": 2, "scope": [], "replaces": "smoke_leaf"})
    mark_agent_pruned(registry, "smoke_leaf", pruning_event_id="P1", replacement="smoke_leaf_v2")
    write_json(tmp_path / "checkpoints" / "smoke_leaf.json", {"verdict": "FAIL"})
    write_json(tmp_path / "checkpoints" / "smoke_leaf_v2.json", {"verdict": "PASS"})

    result = merge_resume_branch(registry=registry, parent_agent="test_branch_agent", out_dir=tmp_path)

    assert result["merge_verdict"] == "PASS"
    assert result["children"] == ["smoke_leaf_v2"]
    assert result["excluded_children"] == [{"agent_id": "smoke_leaf", "reason": "pruned"}]


def test_explicit_attempt_to_merge_pruned_leaf_fails(tmp_path: pathlib.Path) -> None:
    registry = initial_registry()
    add_agent(registry, {"action_id": "S1", "parent_agent": "main_agent", "new_agent_id": "branch", "role": "Branch", "depth": 1, "scope": []})
    add_agent(registry, {"action_id": "S2", "parent_agent": "branch", "new_agent_id": "old_leaf", "role": "Leaf", "depth": 2, "scope": []})
    mark_agent_pruned(registry, "old_leaf", pruning_event_id="P1")

    result = merge_resume_branch(registry=registry, parent_agent="branch", out_dir=tmp_path, requested_children=["old_leaf"])

    assert result["classification"] == "pruned_leaf_used_in_merge"
    assert result["merge_verdict"] == "FAIL"


def test_integration_route_path_ignores_query_and_fragment() -> None:
    namespace: dict[str, object] = {"__file__": "app/routes.py"}
    exec(_integration_files()["app/routes.py"], namespace)

    route_path = namespace["route_path"]
    assert route_path("/search?q=test") == "search"
    assert route_path("/tasks?foo=bar#section") == "tasks"
    assert route_path("/unknown?q=test") == "dashboard"
