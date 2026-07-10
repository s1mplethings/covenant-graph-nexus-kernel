from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_goal_alignment import evaluate_goal_alignment
from scripts.agent_tree_shared_context import create_shared_context


def test_goal_alignment_rejects_drifted_video_workbench_plan() -> None:
    context = create_shared_context("Local AI Knowledge Studio", "Local AI Knowledge Studio")

    result = evaluate_goal_alignment(context, "Local Video Material Workbench")

    assert result["verdict"] == "FAIL"
    assert not result["can_continue"]


def test_goal_alignment_accepts_knowledge_studio_plan() -> None:
    context = create_shared_context("Local AI Knowledge Studio", "Local AI Knowledge Studio")

    result = evaluate_goal_alignment(
        context,
        "document import + knowledge base + search + reports + tasks + local model adapter",
    )

    assert result["verdict"] == "PASS"
    assert result["can_continue"]
