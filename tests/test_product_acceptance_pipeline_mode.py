from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import product_acceptance


def stage(index: int) -> dict[str, str]:
    name = [
        "input_discovery",
        "asset_manifest",
        "metadata_probe",
        "segment_index",
        "evidence_scoring",
        "candidate_selection",
        "export_planning",
        "package_export",
        "report_generation",
        "cold_replay",
    ][index - 1]
    artifact = f"artifacts/stages/{index:02d}_{name}.json" if index <= 8 else ("artifacts/run_report.json" if index == 9 else "artifacts/cold_replay_report.json")
    return {
        "stage_name": f"{index:02d}_{name}",
        "input_schema": "input",
        "output_schema": "output",
        "artifact_path": artifact,
        "validation_rule": "validate output contract",
        "failure_mode": "fail closed",
        "unit_test": f"test_{name}",
    }


def make_pipeline_project(root: pathlib.Path) -> pathlib.Path:
    project = root / "pipeline"
    for directory in ("src", "tests", "examples/input", "examples/output", "artifacts/stages"):
        (project / directory).mkdir(parents=True, exist_ok=True)
    (project / "README.md").write_text(
        "# Local Media Evidence Pipeline\n\nInput manifest metadata segment scoring candidate export report cold replay verify.\n",
        encoding="utf-8",
    )
    (project / "DELIVERY_NOTES.md").write_text("Pipeline delivery notes\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text(
        "commands_run:\n- powershell ./verify.ps1\nunit_tests: 30\ncontract_tests: 15\nintegration_tests: 5\ntotal_tests: 50\nverify script passed\nsample run passed\ncold replay passed\n",
        encoding="utf-8",
    )
    (project / "verify.ps1").write_text("Write-Output 'ok'\n", encoding="utf-8")
    stages = [stage(index) for index in range(1, 11)]
    (project / "pipeline_manifest.json").write_text(json.dumps({"stages": stages}), encoding="utf-8")
    (project / "acceptance_matrix.json").write_text(
        json.dumps(
            {
                "test_counts": {"unit_tests": 30, "contract_tests": 15, "integration_tests": 5, "total_tests": 50},
                "sample_run_passed": True,
                "cold_replay_passed": True,
                "verify_script_passed": True,
            }
        ),
        encoding="utf-8",
    )
    for item in stages:
        artifact = project / item["artifact_path"]
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps({"status": "pass", "stage_name": item["stage_name"]}), encoding="utf-8")
    return project


def make_crud_demo(root: pathlib.Path) -> pathlib.Path:
    project = root / "crud"
    project.mkdir()
    (project / "README.md").write_text("# Todo CRUD\n\nCreate read update delete tasks.\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("total_tests: 8\n", encoding="utf-8")
    return project


def test_pipeline_acceptance_rejects_crud_demo() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        report = product_acceptance.evaluate_product_acceptance(make_crud_demo(pathlib.Path(temp_dir)), pipeline_mode=True)

    assert report["status"] == "fail"
    assert report["recommendation"] == "NEEDS_REWORK"
    assert report["reason"] == "not_pipeline_scale_project"


def test_pipeline_acceptance_requires_sample_run() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_pipeline_project(pathlib.Path(temp_dir))
        matrix = json.loads((project / "acceptance_matrix.json").read_text(encoding="utf-8"))
        matrix["sample_run_passed"] = False
        (project / "acceptance_matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        report = product_acceptance.evaluate_product_acceptance(project, pipeline_mode=True)

    assert report["status"] == "fail"
    assert "sample_run_not_passed" in report["missing_core_features"]


def test_pipeline_acceptance_requires_cold_replay() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_pipeline_project(pathlib.Path(temp_dir))
        matrix = json.loads((project / "acceptance_matrix.json").read_text(encoding="utf-8"))
        matrix["cold_replay_passed"] = False
        (project / "acceptance_matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        report = product_acceptance.evaluate_product_acceptance(project, pipeline_mode=True)

    assert report["status"] == "fail"
    assert "cold_replay_not_passed" in report["missing_core_features"]


def test_pipeline_acceptance_requires_50_plus_tests() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_pipeline_project(pathlib.Path(temp_dir))
        matrix = json.loads((project / "acceptance_matrix.json").read_text(encoding="utf-8"))
        matrix["test_counts"]["total_tests"] = 49
        (project / "acceptance_matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        (project / "TEST_REPORT.md").write_text("unit_tests: 30\ncontract_tests: 15\nintegration_tests: 4\ntotal_tests: 49\n", encoding="utf-8")
        report = product_acceptance.evaluate_product_acceptance(project, pipeline_mode=True)

    assert report["status"] == "fail"
    assert report["test_count"] == 49
    assert "total_tests_lt_50" in report["missing_core_features"]


def test_pipeline_acceptance_passes_complexity_scale_project() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        report = product_acceptance.evaluate_product_acceptance(make_pipeline_project(pathlib.Path(temp_dir)), pipeline_mode=True)

    assert report["status"] == "pass"
    assert report["pipeline_stage_count"] == 10
    assert report["artifact_contract_count"] == 10
    assert report["commercial_ready"] is True
