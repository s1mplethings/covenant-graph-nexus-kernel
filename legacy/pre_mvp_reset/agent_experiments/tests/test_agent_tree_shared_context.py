from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_shared_context import create_shared_context


GOAL = "本地 AI 知识工作台，导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"


def test_shared_context_for_local_ai_knowledge_studio_is_clean() -> None:
    context = create_shared_context("Local AI Knowledge Studio", GOAL)

    assert context["project_name"] == "Local AI Knowledge Studio"
    assert context["target_project_model"]["mode"] == "local_model"
    assert context["cgkn_backend"]["mode"] == "api"
    assert "鉴挂" in context["forbidden_context_terms"]
    assert "背景" in context["forbidden_context_terms"]

    user_goal_text = json.dumps(
        {
            "project_name": context["project_name"],
            "user_goal": context["user_goal"],
            "allowed_context_terms": context["allowed_context_terms"],
            "acceptance_contract": context["acceptance_contract"],
        },
        ensure_ascii=False,
    )
    assert "video workbench" not in user_goal_text.lower()
    assert "鉴挂" not in user_goal_text
    assert "背景立绘" not in user_goal_text
