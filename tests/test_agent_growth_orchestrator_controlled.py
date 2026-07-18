from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_growth_orchestrator import run_controlled_dynamic_growth


GOAL = "做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"


def test_controlled_dynamic_orchestrator_grows_tree_and_delivers(tmp_path: pathlib.Path) -> None:
    result = run_controlled_dynamic_growth(goal=GOAL, project_name="Local AI Knowledge Studio", out_dir=tmp_path)

    assert result["verdict"] == "NEEDS_REWORK"
    assert (tmp_path / "agent_tree_registry.json").exists()
    assert (tmp_path / "spawn_actions.jsonl").exists()
    assert (tmp_path / "scope_contracts").exists()
    assert (tmp_path / "checkpoints").exists()
    assert (tmp_path / "merge_results").exists()
    for branch in ("backend_branch_agent", "frontend_branch_agent", "test_branch_agent"):
        merge = json.loads((tmp_path / "merge_results" / f"{branch}.json").read_text(encoding="utf-8"))
        assert merge["merge_verdict"] == "PASS"
    assert json.loads((tmp_path / "checkpoints" / "integration_agent.json").read_text(encoding="utf-8"))["verdict"] == "PASS"
    gate = json.loads((tmp_path / "contract_checks" / "public_delivery_gate.json").read_text(encoding="utf-8"))
    assert gate["delivery_allowed"] is False
    assert not (tmp_path / "generated_project" / "final_project_bundle.zip").exists()
