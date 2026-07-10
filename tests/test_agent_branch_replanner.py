from __future__ import annotations

import pathlib

from scripts.agent_branch_replanner import replan_branch
from scripts.agent_growth_merge_protocol import merge_branch_results
from scripts.agent_tree_contracts import write_json
from scripts.agent_tree_registry import add_agent, agent_by_id, initial_registry


def _registry() -> dict:
    registry = initial_registry()
    add_agent(
        registry,
        {
            "action_id": "S0001",
            "parent_agent": "main_agent",
            "new_agent_id": "backend_branch_agent",
            "role": "BackendBranchAgent",
            "depth": 1,
            "scope": [],
        },
    )
    add_agent(
        registry,
        {
            "action_id": "S0002",
            "parent_agent": "backend_branch_agent",
            "new_agent_id": "task_service_leaf",
            "role": "TaskServiceLeafAgent",
            "depth": 2,
            "scope": ["app/services/task_service.py", "tests/test_task_service.py"],
        },
    )
    return registry


def _signal() -> dict[str, object]:
    return {
        "pruning_event_id": "P0001",
        "from_leaf": "task_service_leaf",
        "to_parent": "backend_branch_agent",
        "failure_type": "test_failed",
    }


def test_replanner_preserves_pruned_leaf_and_spawns_replacement(tmp_path: pathlib.Path) -> None:
    registry = _registry()
    replan = replan_branch(
        out_dir=tmp_path,
        registry=registry,
        signal=_signal(),
        action="spawn_replacement_leaf",
        new_leaf_id="task_service_leaf_v2",
    )

    original = agent_by_id(registry, "task_service_leaf")
    replacement = agent_by_id(registry, "task_service_leaf_v2")
    assert original["status"] == "pruned"
    assert original["pruned_by"] == "P0001"
    assert original["replacement"] == "task_service_leaf_v2"
    assert replacement["status"] == "active"
    assert replacement["replaces"] == "task_service_leaf"
    assert replan["context_reduced"] is True


def test_replacement_merge_excludes_pruned_original(tmp_path: pathlib.Path) -> None:
    registry = _registry()
    replan_branch(
        out_dir=tmp_path,
        registry=registry,
        signal=_signal(),
        action="spawn_replacement_leaf",
        new_leaf_id="task_service_leaf_v2",
    )
    write_json(tmp_path / "checkpoints" / "task_service_leaf.json", {"verdict": "FAIL"})
    write_json(tmp_path / "checkpoints" / "task_service_leaf_v2.json", {"verdict": "PASS"})

    merge = merge_branch_results(registry=registry, parent_agent="backend_branch_agent", out_dir=tmp_path)

    assert merge["merge_verdict"] == "PASS"
    assert merge["children"] == ["task_service_leaf_v2"]
    assert merge["excluded_children"] == [{"agent_id": "task_service_leaf", "reason": "pruned"}]


def test_split_prunes_original_and_spawns_smaller_children(tmp_path: pathlib.Path) -> None:
    registry = _registry()
    result = replan_branch(
        out_dir=tmp_path,
        registry=registry,
        signal=_signal(),
        action="split_leaf_into_smaller_leaves",
        new_children=["task_storage_leaf", "task_api_leaf"],
    )

    assert result["new_children"] == ["task_storage_leaf", "task_api_leaf"]
    assert agent_by_id(registry, "task_service_leaf")["status"] == "pruned"
    assert agent_by_id(registry, "task_storage_leaf")["replaces"] == "task_service_leaf"
