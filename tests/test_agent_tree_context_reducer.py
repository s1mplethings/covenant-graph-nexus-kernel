from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_context_reducer import reduce_context
from scripts.agent_tree_shared_context import create_shared_context


def test_context_reducer_removes_legacy_project_pollution() -> None:
    context = create_shared_context(
        "Local AI Knowledge Studio",
        "document import knowledge base search reports tasks local model adapter",
    )
    local = reduce_context(
        context,
        agent_id="backend_leaf",
        stage="backend_services",
        raw_context="Local AI Knowledge Studio document import knowledge base search reports tasks + 视频素材 + 鉴挂判别 + 背景立绘 + 鼠标键盘动作",
    )

    joined = " ".join(local["allowed_context_terms"] + [local["user_goal_summary"]] + local["required_files"])
    for term in ("document import", "knowledge base", "search", "reports", "tasks"):
        assert term in joined
    for forbidden in ("视频", "鉴挂", "背景", "立绘", "鼠标键盘动作"):
        assert forbidden not in local["user_goal_summary"]
    assert not any("video" in item.lower() for item in local["required_files"])
