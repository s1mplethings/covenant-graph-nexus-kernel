from __future__ import annotations

import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_contracts import read_jsonl
from scripts.agent_tree_orchestrator import run_controlled_agent_tree


GOAL = "做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"


def test_controlled_orchestrator_generates_stepwise_runnable_project(tmp_path: pathlib.Path) -> None:
    result = run_controlled_agent_tree(
        goal=GOAL,
        project_name="Local AI Knowledge Studio",
        out_dir=tmp_path,
        provider_mode="controlled",
    )

    assert result["verdict"] == "NEEDS_REWORK"
    assert (tmp_path / "shared_context.json").exists()
    assert (tmp_path / "agent_build_dag.json").exists()
    assert (tmp_path / "agent_actions.jsonl").exists()
    for stage in ("foundation", "backend_services", "frontend_views", "tests", "visual", "delivery"):
        checkpoint = json.loads((tmp_path / "checkpoints" / f"{stage}.json").read_text(encoding="utf-8"))
        assert checkpoint["verdict"] == ("FAIL" if stage == "delivery" else "PASS")
    project = tmp_path / "generated_project"
    assert (project / "app" / "main.py").exists()
    assert json.loads((project / "test_execution.json").read_text(encoding="utf-8"))["verdict"] == "PASS"
    assert not (project / "visual_evidence.json").exists()
    assert not (project / "final_project_bundle.zip").exists()
    gate = json.loads((tmp_path / "contract_checks" / "public_delivery_gate.json").read_text(encoding="utf-8"))
    assert gate["delivery_allowed"] is False
    assert read_jsonl(tmp_path / "agent_actions.jsonl")
