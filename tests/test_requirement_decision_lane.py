from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import requirement_decision_lane


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_rough_goal_generates_requirement_decision_artifacts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        run_dir = pathlib.Path(temp_dir) / "run"
        result = requirement_decision_lane.run_requirement_decision("我想要一个本地视频素材处理工具", run_dir)
        req_dir = run_dir / "requirement_decision"

        assert result["status"] == "PASS"
        for name in [
            "customer_goal_brief.md",
            "need_interpretations.json",
            "candidate_requirements.json",
            "requirement_scorecard.json",
            "selected_requirement.json",
            "rejected_requirements.md",
            "mvp_scope.md",
            "non_goals.md",
            "acceptance_contract.json",
            "customer_decision_summary.md",
        ]:
            assert (req_dir / name).exists()
            assert (req_dir / name).stat().st_size > 0

        candidates = read_json(req_dir / "candidate_requirements.json")["candidates"]
        assert len(candidates) >= 3
        for candidate in candidates:
            assert "customer_value_score" in candidate
            assert "clarity_score" in candidate
            assert "delivery_feasibility" in candidate
            assert "testability_score" in candidate

        selected = read_json(req_dir / "selected_requirement.json")
        contract = read_json(req_dir / "acceptance_contract.json")
        assert selected["selected_requirement_id"]
        assert selected["selected_requirement_id"] == "local_video_material_workbench_requirement"
        assert contract["contract_id"] == "requirement_acceptance_contract_v1"
        assert "delivery_pass_without_zip_or_screenshot" in contract["forbidden_shortcuts"]


def test_small_demo_and_high_fake_pass_requirement_are_not_selected() -> None:
    interpretations = requirement_decision_lane.generate_need_interpretations("Need a complex local video workbench")
    candidates = requirement_decision_lane.generate_candidate_requirements("Need a complex local video workbench", interpretations)
    scorecard = requirement_decision_lane.score_candidate_requirements(candidates, {"complex_goal": True})
    selected = requirement_decision_lane.select_requirement(candidates, scorecard, {"complex_goal": True})

    assert selected["selected_requirement_id"] not in {"single_static_page_demo_requirement", "cloud_ai_autopilot_requirement"}
    decisions = {score["candidate_id"]: score for score in scorecard["scores"]}
    assert decisions["single_static_page_demo_requirement"]["decision"] == "reject"
    assert decisions["cloud_ai_autopilot_requirement"]["decision"] == "reject"


def test_load_requirement_acceptance_contract() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        run_dir = pathlib.Path(temp_dir) / "run"
        requirement_decision_lane.run_requirement_decision("我想做一个本地资料整理和研究工作台", run_dir)

        contract = requirement_decision_lane.load_requirement_acceptance_contract(run_dir)

    assert contract["contract_id"] == "requirement_acceptance_contract_v1"
    assert "required_requirement_artifacts" in contract


def test_delivery_video_does_not_change_task_board_product_domain() -> None:
    goal = (
        "构建一个完全本地运行的单页任务看板 Web 项目，支持任务新增、状态切换、删除、筛选和 localStorage 持久化。"
        "完整验收必须运行测试、生成真实浏览器截图和工作流演示视频，最后生成 final_project_bundle.zip。"
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        result = requirement_decision_lane.run_requirement_decision(goal, pathlib.Path(temp_dir) / "run")

    selected = result["selected_requirement"]
    interpretations = result["need_interpretations"]["interpreted_needs"]
    assert selected["selected_requirement_id"] == "local_task_board_requirement"
    assert interpretations[0]["id"] == "task_board_need"
    assert all(item["id"] != "media_workflow_need" for item in interpretations)


def test_chinese_video_slicing_goal_is_classified_as_media_requirement() -> None:
    goal = "为视频创作者构建本地 AI 切片工作台，处理长视频并导出候选片段。"
    with tempfile.TemporaryDirectory() as temp_dir:
        result = requirement_decision_lane.run_requirement_decision(goal, pathlib.Path(temp_dir) / "run")

    assert requirement_decision_lane.goal_has_media_product(goal) is True
    assert result["selected_requirement"]["selected_requirement_id"] == "local_video_material_workbench_requirement"


def test_visual_novel_goal_selects_visual_novel_requirement_and_not_media() -> None:
    goal = "生成大型 VN 视觉小说创作工作室，支持剧情树、背景图片生成、透明人物立绘和分支预览。"
    with tempfile.TemporaryDirectory() as temp_dir:
        result = requirement_decision_lane.run_requirement_decision(goal, pathlib.Path(temp_dir) / "run")

    assert requirement_decision_lane.goal_has_visual_novel_product(goal) is True
    assert requirement_decision_lane.goal_has_media_product(goal) is False
    assert result["selected_requirement"]["selected_requirement_id"] == "local_visual_novel_studio_requirement"
    assert result["need_interpretations"]["interpreted_needs"][0]["id"] == "visual_novel_authoring_need"


def test_image_generation_without_video_terms_does_not_select_video_requirement() -> None:
    goal = "构建图片生成和透明角色立绘资产库，不需要视频、音频、转录或切片。"
    with tempfile.TemporaryDirectory() as temp_dir:
        result = requirement_decision_lane.run_requirement_decision(goal, pathlib.Path(temp_dir) / "run")

    assert requirement_decision_lane.goal_has_media_product(goal) is False
    assert result["selected_requirement"]["selected_requirement_id"] != "local_video_material_workbench_requirement"
