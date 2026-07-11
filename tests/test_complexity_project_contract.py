from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import complexity_project_contract_check
from scripts import discovery_selection_lane
from scripts import product_acceptance


def write(path: pathlib.Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_contract_check_passes_discovery_artifacts_without_project_scope() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        run_dir = pathlib.Path(temp_dir) / "run"
        discovery_selection_lane.run_discovery_selection("Need a complex local video workbench", run_dir / "discovery")

        result = complexity_project_contract_check.validate(run_dir=run_dir)

    assert result["status"] == "pass"
    assert result["metadata"]["contract_id"] == "complexity_project_contract_v1"


def test_missing_contract_makes_strict_product_acceptance_needs_rework() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "project"
        write(project / "README.md", "# Project\n")
        report = product_acceptance.evaluate_product_acceptance(
            project,
            run_dir=pathlib.Path(temp_dir) / "run",
            require_complexity_contract=True,
        )

    assert report["status"] == "fail"
    assert report["recommendation"] == "NEEDS_REWORK"
    assert "complexity_project_contract.json_missing" in report["missing_core_features"]


def test_missing_orchestrator_stages_and_shared_core_cannot_pass_complex_project() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        run_dir = root / "run"
        project = root / "project"
        discovery_selection_lane.run_discovery_selection("Need a complex local video workbench", run_dir / "discovery")
        for name in ("product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md", "README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
            write(project / name, f"# {name}\n")

        report = product_acceptance.evaluate_product_acceptance(
            project,
            run_dir=run_dir,
            require_complexity_contract=True,
        )

    assert report["status"] == "fail"
    assert "orchestrator.py_missing" in report["missing_core_features"]
    assert "stages.py_missing" in report["missing_core_features"]
    assert "cli_entry_missing" in report["missing_core_features"]
    assert "gui_entry_missing" in report["missing_core_features"]
    assert "gui_cli_shared_core_missing" in report["missing_core_features"]
    assert "final_project_bundle.zip_missing" in report["missing_core_features"]


def test_contract_requires_planning_core_stages_artifacts_and_delivery_evidence() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        run_dir = pathlib.Path(temp_dir) / "run"
        discovery_selection_lane.run_discovery_selection("Need a complex local video workbench", run_dir / "discovery")
        contract = json.loads((run_dir / "discovery" / "complexity_project_contract.json").read_text(encoding="utf-8"))

    assert "product_brief.md" in contract["required_planning_docs"]
    assert "orchestrator.py" in contract["required_core_files"]
    assert "stages.py" in contract["required_core_files"]
    assert contract["required_pipeline_stages"]
    assert contract["required_stage_artifacts"]
    assert "final_project_bundle.zip" in contract["required_delivery_evidence"]
    assert "screenshot" in contract["required_delivery_evidence"]
