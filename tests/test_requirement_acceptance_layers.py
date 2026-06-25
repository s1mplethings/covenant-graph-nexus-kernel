from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import product_acceptance
from scripts import requirement_acceptance_check
from scripts import requirement_decision_lane


def write(path: pathlib.Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_requirement_decision_pass_does_not_make_delivery_pass() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        run_dir = root / "run"
        project = root / "project"
        requirement_decision_lane.run_requirement_decision("我想要一个本地视频素材处理工具", run_dir)
        write(project / "README.md", "# Project\n")
        write(project / "TEST_REPORT.md", "commands_run:\n- python -m pytest\nexit_code: 0\n")
        write(project / "DELIVERY_NOTES.md", "# Notes\n")

        layers = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=run_dir)
        report = product_acceptance.evaluate_product_acceptance(project, run_dir=run_dir)

    assert layers["requirement_decision_status"] == "PASS"
    assert layers["delivery_status"] == "NEEDS_REWORK"
    assert layers["overall_status"] == "NEEDS_REWORK"
    assert report["requirement_decision_status"] == "PASS"
    assert report["delivery_status"] == "NEEDS_REWORK"
    assert report["overall_status"] == "NEEDS_REWORK"


def test_missing_requirement_decision_fails_requirement_layer() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "project"
        write(project / "README.md", "# Project\n")

        layers = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=pathlib.Path(temp_dir) / "run")

    assert layers["requirement_decision_status"] == "FAIL"
    assert "customer_goal_brief.md_missing" in layers["known_gaps"]


def test_requirement_pass_does_not_make_product_contract_pass() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        run_dir = root / "run"
        project = root / "project"
        requirement_decision_lane.run_requirement_decision("我想要一个本地视频素材处理工具", run_dir)
        (run_dir / "discovery").mkdir(parents=True, exist_ok=True)
        write(run_dir / "discovery" / "complexity_project_contract.json", '{"contract_id":"complexity_project_contract_v1","required_stage_artifacts":[]}\n')
        write(project / "README.md", "# Project\n")

        layers = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=run_dir)

    assert layers["requirement_decision_status"] == "PASS"
    assert layers["product_contract_status"] != "PASS"
    assert layers["delivery_status"] == "NEEDS_REWORK"
    assert "planning_contract_gate" in layers["checks"]
