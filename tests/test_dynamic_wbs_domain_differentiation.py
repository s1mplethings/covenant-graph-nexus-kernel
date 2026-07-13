from __future__ import annotations

import pathlib

from scripts.agent_growth_planner import plan_dynamic_growth
from scripts.agent_tree_contracts import read_json
from scripts.agent_tree_shared_context import create_shared_context


def _planned_run(tmp_path: pathlib.Path, name: str, goal: str) -> tuple[dict, dict, set[str], set[str]]:
    out_dir = tmp_path / name
    registry = plan_dynamic_growth(create_shared_context(name, goal), out_dir)
    plan = read_json(out_dir / "project_plan.json", {})
    summary = read_json(out_dir / "growth_plan_summary.json", {})
    assert summary["planning_mode"] == "dynamic_wbs"
    agent_ids = {agent["agent_id"] for agent in registry["agents"]}
    scope_files = {
        path.name
        for path in (out_dir / "scope_contracts").glob("*.json")
        if path.name != "main_agent.json"
    }
    return plan, summary, agent_ids, scope_files


def test_dynamic_wbs_changes_agent_tree_scope_and_critical_path_by_domain(tmp_path: pathlib.Path) -> None:
    knowledge_plan, knowledge_summary, knowledge_agents, knowledge_scopes = _planned_run(
        tmp_path,
        "Local AI Knowledge Studio",
        "导入资料、知识库检索、任务化跟踪、生成报告，并支持本地模型适配层和界面",
    )
    studio_plan, studio_summary, studio_agents, studio_scopes = _planned_run(
        tmp_path,
        "Indie Studio Operations Hub",
        "独立游戏工作室生产管理中心，管理 milestone、asset pipeline、capacity budget、release dashboard",
    )
    media_plan, media_summary, media_agents, media_scopes = _planned_run(
        tmp_path,
        "Batch Media Analysis Tool",
        "本地批量媒体分析与报告工具，处理 video transcript metadata batch report export",
    )

    assert knowledge_summary["domain"] == "knowledge_studio"
    assert studio_summary["domain"] == "studio_operations_hub"
    assert media_summary["domain"] == "media_analysis_tool"
    assert {knowledge_summary["domain"], studio_summary["domain"], media_summary["domain"]} == {
        "knowledge_studio",
        "studio_operations_hub",
        "media_analysis_tool",
    }

    assert "search_service_leaf" in knowledge_agents
    assert "studio_asset_pipeline_leaf" in studio_agents
    assert "media_ingest_leaf" in media_agents
    assert "studio_asset_pipeline_leaf" not in knowledge_agents
    assert "media_ingest_leaf" not in studio_agents
    assert "search_service_leaf" not in media_agents

    assert "search_service_leaf.json" in knowledge_scopes
    assert "studio_asset_pipeline_leaf.json" in studio_scopes
    assert "media_ingest_leaf.json" in media_scopes
    assert knowledge_scopes != studio_scopes
    assert studio_scopes != media_scopes
    assert knowledge_scopes != media_scopes

    assert knowledge_plan["critical_path"] != studio_plan["critical_path"]
    assert studio_plan["critical_path"] != media_plan["critical_path"]
    assert knowledge_plan["critical_path"] != media_plan["critical_path"]
