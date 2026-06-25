from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import discovery_selection_lane


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
    assert contract["required_planning_docs"] == [
        "product_brief.md",
        "technical_plan.md",
        "interaction_design.md",
        "acceptance_matrix.md",
    ]
    assert contract["required_core_files"] == ["orchestrator.py", "stages.py"]
    assert len(contract["required_pipeline_stages"]) >= 6
    assert len(contract["required_stage_artifacts"]) >= 6


def test_low_complexity_and_high_dependency_candidates_are_not_selected() -> None:
    candidates = discovery_selection_lane.generate_candidates("make something useful with local files", count=5)
    selected = discovery_selection_lane.select_candidate(candidates)

    assert selected is not None
    assert selected["id"] not in {"single_page_status_demo", "cloud_ai_autopilot_suite"}
    rejected = {candidate["id"]: discovery_selection_lane.rejection_reasons(candidate) for candidate in candidates}
    assert "complexity_score_lt_60" in rejected["single_page_status_demo"]
    assert "external_dependency_high_without_honest_degraded_mode" in rejected["cloud_ai_autopilot_suite"]


def test_rejected_options_artifact_records_non_selected_directions() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        discovery_dir = pathlib.Path(temp_dir) / "discovery"
        discovery_selection_lane.run_discovery_selection("Build a local video project", discovery_dir, candidate_count=5)
        rejected = (discovery_dir / "rejected_options.md").read_text(encoding="utf-8")

    assert "Rejected Options" in rejected
    assert "single_page_status_demo" in rejected
    assert "cloud_ai_autopilot_suite" in rejected
