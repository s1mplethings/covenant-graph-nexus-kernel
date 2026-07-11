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
