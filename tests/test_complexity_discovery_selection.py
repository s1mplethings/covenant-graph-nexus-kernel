from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import complexity_project_contract_check
from scripts import discovery_selection_lane
from scripts import requirement_decision_lane


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_rough_goal_generates_candidates_scorecard_selection_and_contract() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        discovery_dir = pathlib.Path(temp_dir) / "discovery"
        result = discovery_selection_lane.run_discovery_selection(
            "Need a complex local video processing workbench with GUI, CLI, artifacts, and degraded mode.",
            discovery_dir,
        )

        candidates = read_json(discovery_dir / "candidate_directions.json")
        scorecard = read_json(discovery_dir / "candidate_scorecard.json")
        selected = read_json(discovery_dir / "selected_project_direction.json")
        contract = read_json(discovery_dir / "complexity_project_contract.json")

    assert result["status"] == "PASS"
    assert 3 <= len(candidates["candidates"]) <= 5
    assert all("complexity_score" in candidate for candidate in candidates["candidates"])
    assert all("delivery_feasibility" in candidate for candidate in candidates["candidates"])
    assert scorecard["scores"]
    assert selected["selected_id"]
    assert "Local Video" in selected["selected_name"]
    assert contract["contract_id"] == "complexity_project_contract_v1"
    assert contract["architecture_mode"] == "goal_driven_local_application"
    assert contract["goal_spec_domain"] == "local_media_workbench"
    assert {"goal_spec.json", "project_plan.json", "acceptance_matrix.md"}.issubset(contract["required_planning_docs"])
    assert "app/main.py" in contract["required_core_files"]
    assert len(contract["required_pipeline_stages"]) >= 6
    assert len(contract["required_stage_artifacts"]) >= 6


def test_low_complexity_and_high_dependency_candidates_are_not_selected() -> None:
    candidates = discovery_selection_lane.generate_candidates("make something useful with local files", count=5)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert selected is None
    rejected = {candidate["id"]: discovery_selection_lane.rejection_reasons(candidate) for candidate in candidates}
    assert "complexity_score_lt_60" in rejected["single_page_status_demo"]
    assert "external_dependency_high_without_honest_degraded_mode" in rejected["cloud_ai_autopilot_suite"]


def test_direct_cli_contract_allows_empty_stage_graph_without_becoming_static_demo() -> None:
    goal = "Build a Notes CLI with add, list, search, and delete commands using atomic JSON storage."
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)
    with tempfile.TemporaryDirectory() as temp_dir:
        discovery_dir = pathlib.Path(temp_dir) / "discovery"
        result = discovery_selection_lane.run_discovery_selection(
            goal,
            discovery_dir,
            goal_spec=spec,
            project_plan=plan,
        )
        contract, blockers = complexity_project_contract_check.validate_discovery(discovery_dir)

    assert result["status"] == "PASS"
    assert blockers == []
    assert contract["architecture_mode"] == "direct_cli_application"
    assert contract["required_pipeline_stages"] == []
    assert contract["required_stage_artifacts"] == []


def test_rejected_options_artifact_records_non_selected_directions() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        discovery_dir = pathlib.Path(temp_dir) / "discovery"
        discovery_selection_lane.run_discovery_selection("Build a local video project", discovery_dir, candidate_count=5)
        rejected = (discovery_dir / "rejected_options.md").read_text(encoding="utf-8")

    assert "Rejected Options" in rejected
    assert "single_page_status_demo" in rejected
    assert "cloud_ai_autopilot_suite" in rejected


def test_media_review_phrase_selects_media_workbench() -> None:
    candidates = discovery_selection_lane.generate_candidates(
        "I need a local-first media review workbench with GUI, CLI, pipeline artifacts, and degraded mode.",
        count=4,
    )
    selected = discovery_selection_lane.select_candidate(candidates)

    assert selected is not None
    assert selected["id"] == "local_video_workbench"


def test_media_evidence_pipeline_selects_media_workbench() -> None:
    goal = (
        "Build a local 8-12 stage media evidence pipeline that imports local media, "
        "extracts metadata, scores evidence, selects candidates, and packages exports."
    )

    candidates = discovery_selection_lane.generate_candidates(goal, count=4)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert discovery_selection_lane.goal_has_media_product(goal) is True
    assert selected is not None
    assert selected["id"] == "local_video_workbench"


def test_media_production_and_review_goal_selects_media_workbench() -> None:
    goal = (
        "I want a local-first media production and review workbench that imports "
        "video and audio, analyzes clips, and exports a project package."
    )

    candidates = discovery_selection_lane.generate_candidates(goal, count=4)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert discovery_selection_lane.goal_has_media_product(goal) is True
    assert selected is not None
    assert selected["id"] == "local_video_workbench"


def test_delivery_video_does_not_select_video_workbench_for_task_board() -> None:
    goal = (
        "构建一个本地任务看板，支持新增、移动、筛选、删除和 localStorage。"
        "验收时需要真实截图、演示视频、测试报告和最终 ZIP。"
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        result = discovery_selection_lane.run_discovery_selection(goal, pathlib.Path(temp_dir) / "discovery", candidate_count=5)

    selected = result["selected_project_direction"]
    contract = result["complexity_project_contract"]
    assert selected["selected_id"] == "local_task_board"
    assert selected["architecture_mode"] == "browser_local_static"
    assert selected["required_complexity_floor"]["requires_cli"] is False
    assert selected["required_complexity_floor"]["min_stage_artifacts"] > 0
    assert "task_board" in contract["required_interfaces"]
    assert "app/main.py" in contract["required_core_files"]
    assert contract["architecture_mode"] == "browser_local_static"
    assert contract["canonical_goal_spec"]["domain"] == "local_task_board"


def test_chinese_video_slicing_goal_selects_video_workbench() -> None:
    goal = "构建一个面向视频创作者的 AI 辅助切片工作台，把长视频转换成可筛选的候选片段。"

    candidates = discovery_selection_lane.generate_candidates(goal, count=4)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert discovery_selection_lane.goal_has_media_product(goal) is True
    assert selected is not None
    assert selected["id"] == "local_video_workbench"


def test_visual_novel_goal_preserves_authoring_domain_instead_of_video_pipeline() -> None:
    goal = "生成大型 VN 视觉小说工作室，支持剧情树、剧情分支、背景生成和人物立绘生成。"

    candidates = discovery_selection_lane.generate_candidates(goal, count=5)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert discovery_selection_lane.goal_has_visual_novel_product(goal) is True
    assert discovery_selection_lane.goal_has_media_product(goal) is False
    assert selected is not None
    assert selected["id"] == "local_visual_novel_studio"
    contract = discovery_selection_lane.build_contract(selected)
    assert contract["architecture_mode"] == "modular_authoring_studio"
    assert "story_tree" in contract["required_interfaces"]
    assert "src/story_model.py" in contract["required_core_files"]
    assert "scene_editor" in contract["required_pipeline_stages"]
    assert "branch_editor" in contract["required_pipeline_stages"]


def test_image_generation_terms_alone_do_not_select_video_processing() -> None:
    goal = "做一个本地图像生成与角色立绘资产工具，不处理视频、音频、转录或剪辑。"

    candidates = discovery_selection_lane.generate_candidates(goal, count=5)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert discovery_selection_lane.goal_has_media_product(goal) is False
    assert selected is not None
    assert selected["id"] != "local_video_workbench"


def test_cs_demo_analysis_goal_selects_goal_derived_specialized_workbench() -> None:
    goal = (
        "Build a CS2 demo integrity analysis project that discovers official platform acquisition "
        "methods, downloads only authorized match demos, parses crosshair and player-position "
        "relationships, and produces explainable anti-cheat review evidence."
    )

    candidates = discovery_selection_lane.generate_candidates(goal, count=5)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert discovery_selection_lane.goal_has_specialized_analysis_product(goal) is True
    assert selected is not None
    assert selected["id"] == "goal_driven_cs2_demo_anomaly_analysis"
    assert selected["pipeline_stages"][0] == "foundation"
    assert "explainable_anomaly_analysis" in selected["pipeline_stages"]
    assert "human_review_reporting" in selected["pipeline_stages"]
