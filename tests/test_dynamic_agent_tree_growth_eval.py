from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_growth_budget import default_growth_budget
from scripts.agent_growth_merge_protocol import merge_branch_results
from scripts.agent_growth_orchestrator import controlled_leaf_build
from scripts.agent_growth_planner import plan_dynamic_growth
from scripts.agent_tree_contracts import read_jsonl
from scripts.agent_tree_registry import agent_by_id
from scripts.agent_tree_shared_context import create_shared_context


def test_scope_violation_injection_blocks_leaf_and_parent_merge(tmp_path: pathlib.Path) -> None:
    registry = plan_dynamic_growth(create_shared_context("Local AI Knowledge Studio", "document import search tasks reports local model adapter"), tmp_path)
    project = tmp_path / "project"
    leaf = agent_by_id(registry, "search_service_leaf")

    checkpoint = controlled_leaf_build(leaf, project_dir=project, out_dir=tmp_path, budget=default_growth_budget(), injected_files=["README.md"])

    assert checkpoint["verdict"] == "FAIL"
    assert any("scope_violation" in issue for issue in checkpoint["issues"])
    feedback = read_jsonl(tmp_path / "feedback_tasks.jsonl")
    assert feedback[-1]["target_agent"] == "search_service_leaf"
    merge = merge_branch_results(registry=registry, parent_agent="backend_branch_agent", out_dir=tmp_path)
    assert merge["merge_verdict"] != "PASS"


def test_needs_split_creates_parent_feedback_without_executing_leaf(tmp_path: pathlib.Path) -> None:
    budget = default_growth_budget()
    registry = plan_dynamic_growth(create_shared_context("Local AI Knowledge Studio", "document import search tasks reports local model adapter"), tmp_path)
    leaf = agent_by_id(registry, "search_service_leaf")
    contract_path = tmp_path / "scope_contracts" / "search_service_leaf.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["allowed_files"] = [f"app/services/too_big_{index}.py" for index in range(budget["max_leaf_expected_files"] + 1)]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint = controlled_leaf_build(leaf, project_dir=tmp_path / "project", out_dir=tmp_path, budget=budget)

    assert checkpoint["verdict"] == "NEEDS_SPLIT"
    assert not (tmp_path / "project" / "app" / "services" / "too_big_0.py").exists()
    feedback = read_jsonl(tmp_path / "feedback_tasks.jsonl")
    assert feedback[-1]["target_agent"] == "backend_branch_agent"
    assert "spawn_smaller_children" in feedback[-1]["allowed_actions"]
