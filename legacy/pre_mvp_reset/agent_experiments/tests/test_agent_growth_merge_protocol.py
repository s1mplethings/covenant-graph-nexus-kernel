from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_growth_merge_protocol import merge_branch_results
from scripts.agent_tree_contracts import write_json
from scripts.agent_tree_registry import add_agent, initial_registry


def test_branch_merge_fails_when_required_child_failed(tmp_path: pathlib.Path) -> None:
    registry = initial_registry()
    add_agent(registry, {"action_id": "S0001", "parent_agent": "main_agent", "new_agent_id": "backend_branch_agent", "role": "BackendBranchAgent", "depth": 1, "scope": []})
    add_agent(registry, {"action_id": "S0002", "parent_agent": "backend_branch_agent", "new_agent_id": "search_service_leaf", "role": "SearchServiceLeafAgent", "depth": 2, "scope": []})
    write_json(tmp_path / "checkpoints" / "search_service_leaf.json", {"agent_id": "search_service_leaf", "verdict": "FAIL"})

    result = merge_branch_results(registry=registry, parent_agent="backend_branch_agent", out_dir=tmp_path)

    assert result["merge_verdict"] == "FAIL"
    assert result["required_children_passed"] is False
