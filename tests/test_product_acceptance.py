from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import product_acceptance


def make_project(root: pathlib.Path) -> pathlib.Path:
    project = root / "project"
    project.mkdir()
    (project / "README.md").write_text("# CSV Dashboard\n\nCSV upload, charts, filters, export.\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("ready for review\n", encoding="utf-8")
    (project / "package.json").write_text("{}", encoding="utf-8")
    return project


def test_product_acceptance_scores_feature_coverage() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        report = product_acceptance.evaluate_product_acceptance(
            project,
            goal="CSV Dashboard upload charts filters export",
            ui_smoke_result={"status": "pass"},
            screenshot_metadata={"valid": True},
            feature_list=["CSV upload", "charts", "filters", "export"],
        )

    assert report["feature_coverage_score"] >= 80
    assert report["product_score"] >= 75


def test_product_acceptance_blocks_missing_core_feature() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        report = product_acceptance.evaluate_product_acceptance(project, goal="inventory barcode scanner", ui_smoke_result={"status": "pass"})

    assert report["status"] == "fail"
    assert "barcode" in report["missing_core_features"]
    assert report["recommendation"] == "NEEDS_REWORK"


def test_low_ux_score_downgrades_to_deliver_with_warnings() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        report = product_acceptance.evaluate_product_acceptance(
            project,
            goal="CSV Dashboard",
            ui_smoke_result={"status": "fail"},
            known_limits=["UI polish limited"],
            feature_list=["CSV Dashboard"],
        )

    assert report["ux_score"] < 60
    assert report["recommendation"] in {"DELIVER_WITH_WARNINGS", "ASK_USER_REVIEW"}


def test_product_acceptance_report_written() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = pathlib.Path(temp_dir) / "product_acceptance_report.json"
        product_acceptance.write_report(path, {"status": "pass"})

        assert path.exists()


def test_product_acceptance_no_evidence_not_evaluated() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "empty"
        project.mkdir()
        report = product_acceptance.evaluate_product_acceptance(
            project,
            goal="commercial readiness project",
            ui_smoke_result={},
            screenshot_metadata={},
            video_metadata={},
            generated_file_manifest=[],
            feature_list=[],
        )

    assert report["status"] == "not_evaluated"
    assert report["reason"] == "NO_PRODUCT_EVIDENCE"
    assert report["commercial_ready"] is False
    assert report["recommendation"] == "COMMERCIAL_BETA"


def test_product_acceptance_empty_candidate_does_not_emit_fake_scores() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "empty_candidate"
        project.mkdir()
        report = product_acceptance.evaluate_product_acceptance(project, goal="commercial readiness project", ui_smoke_result={"status": "pass"})

    assert report["status"] == "not_evaluated"
    assert report["product_score"] is None
    assert report["feature_coverage_score"] is None
    assert report["ux_score"] is None
    assert report["maintainability_score"] is None
    assert report["missing_core_features"] == []
