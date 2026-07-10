from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_shared_context import build_goal_specific_acceptance_contract, create_shared_context


def test_local_studio_operations_contract_covers_current_goal() -> None:
    goal = (
        "Build a Local Studio Operations Hub for assets, production tasks, bugs, builds, "
        "release checklist, team roles, search, import/export, tests, screenshots, and bundle."
    )

    contract = build_goal_specific_acceptance_contract("Local Studio Operations Hub", goal)
    required = " ".join(contract["required_capabilities"]).lower()

    assert contract["domain"] == "local_studio_operations_hub"
    for term in (
        "asset library",
        "bugs and issues",
        "build and release",
        "release checklist",
        "team members",
        "search and filtering",
        "import and export",
        "screenshots",
        "final bundle",
    ):
        assert term in required
    assert "knowledge base" not in required


def test_shared_context_uses_goal_specific_contract_without_knowledge_drift() -> None:
    context = create_shared_context(
        "Local Studio Operations Hub",
        "local-first studio hub for production tasks, assets, bugs, releases, docs, team roles, search, import/export",
    )
    required = " ".join(context["acceptance_contract"]).lower()

    assert context["goal_specific_acceptance_contract"]["domain"] == "local_studio_operations_hub"
    assert "asset library" in required
    assert "knowledge base" not in required
    allowed = " ".join(context["allowed_context_terms"]).lower()
    assert "asset library" in allowed
    assert "knowledge base" not in allowed


def test_knowledge_studio_contract_is_still_available_for_knowledge_goal() -> None:
    context = create_shared_context(
        "Local AI Knowledge Studio",
        "本地 AI 知识工作台，导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层",
    )
    required = " ".join(context["acceptance_contract"]).lower()

    assert context["goal_specific_acceptance_contract"]["domain"] == "local_ai_knowledge_studio"
    assert "knowledge base" in required
    assert "local model adapter" in required
