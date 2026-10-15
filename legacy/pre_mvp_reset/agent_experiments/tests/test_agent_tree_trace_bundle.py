from __future__ import annotations

import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_orchestrator import run_controlled_agent_tree


def test_trace_bundle_contains_replayable_agent_tree_evidence(tmp_path: pathlib.Path) -> None:
    result = run_controlled_agent_tree(
        goal="做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层",
        project_name="Local AI Knowledge Studio",
        out_dir=tmp_path,
        provider_mode="controlled",
    )
    bundle = pathlib.Path(result["trace_bundle"])

    assert bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
    for required in (
        "00_INDEX.md",
        "shared_context.json",
        "agent_build_dag.json",
        "agent_actions.jsonl",
        "feedback_tasks.jsonl",
        "project_tree.txt",
        "final_verdict.json",
    ):
        assert required in names
    assert any(name.startswith("checkpoints/") for name in names)
    assert any(name.startswith("contract_checks/") for name in names)
