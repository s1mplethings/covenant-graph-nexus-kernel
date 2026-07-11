from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_growth_budget import default_growth_budget
from scripts.agent_spawn_protocol import create_spawn_action, validate_spawn_action
from scripts.agent_tree_registry import initial_registry


def test_spawn_protocol_writes_structured_spawn_action(tmp_path: pathlib.Path) -> None:
    action = create_spawn_action(
        out_dir=tmp_path,
        registry=initial_registry(),
        budget=default_growth_budget(),
        parent_agent="main_agent",
        new_agent_id="backend_branch_agent",
        role="BackendBranchAgent",
        depth=1,
        reason="Project requires backend services",
        scope=["backend module planning"],
        expected_outputs=["backend_branch_plan.json"],
        verification=["scope_contract_valid", "children_within_budget"],
    )

    assert not validate_spawn_action(action)
    assert action["action_id"] == "S0001"
    assert action["action"] == "spawn_agent"
    assert (tmp_path / "spawn_actions.jsonl").exists()
