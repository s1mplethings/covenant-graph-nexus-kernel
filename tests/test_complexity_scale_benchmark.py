from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_complexity_scale_benchmark
from scripts import run_complexity_scale_workbench_benchmark


def test_complexity_scale_spec_requires_8_plus_stages() -> None:
    spec = run_complexity_scale_benchmark.read_json(ROOT / "benchmarks" / "complexity_scale_pipeline_benchmark.json")
    result = run_complexity_scale_benchmark.validate_spec(spec)

    assert result["status"] == "pass"
    assert result["stage_count"] >= 8
    assert result["minimum_tests"]["total_tests"] >= 50


def test_complexity_scale_spec_requires_contract_artifacts() -> None:
    spec = run_complexity_scale_benchmark.read_json(ROOT / "benchmarks" / "complexity_scale_pipeline_benchmark.json")
    required_fields = set(spec["stage_contract_required_fields"])

    assert required_fields >= {"stage_name", "input_schema", "output_schema", "artifact_path", "validation_rule", "failure_mode", "unit_test"}
    assert all(required_fields.issubset(stage.keys()) for stage in spec["canonical_stages"])
    assert "artifacts/cold_replay_report.json" in spec["required_artifacts"]


def test_complexity_scale_benchmark_report_written(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        report_path = root / "complexity_report.json"
        monkeypatch.setattr(
            run_complexity_scale_benchmark.provider_resilience,
            "provider_preflight",
            lambda **kwargs: {"status": "fail", "metadata": {"live_generation_allowed": False, "commercial_blocker": "provider_quota"}},
        )
        monkeypatch.setattr(
            run_complexity_scale_benchmark.run_commercial_readiness,
            "assess_commercial_readiness",
            lambda **kwargs: {"commercial_status": "COMMERCIAL_BETA", "beta_reasons": ["provider_quota"], "remaining_blockers": []},
        )

        report = run_complexity_scale_benchmark.run_benchmark(report_path=report_path, live=False, out_dir=root / "candidate", run_dir=root / "run")
        written = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["complexity_scale_benchmark"]["benchmark_spec"]["status"] == "pass"
    assert written["complexity_scale_benchmark"]["candidate_materialized"] is False
    assert written["fake_pass_protection"]["candidate_as_final_rejected"] is True


def test_complexity_scale_final_gate_still_rejects_candidate_bundle() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        candidate = pathlib.Path(temp_dir) / "candidate"
        candidate.mkdir()
        (candidate / "README.md").write_text("# Candidate\n", encoding="utf-8")

        rejected = run_complexity_scale_benchmark.candidate_as_final_rejected(candidate)

    assert rejected is True


def test_workbench_benchmark_reports_planning_contract_gate(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    run_complexity_scale_workbench_benchmark.requirement_decision_lane.run_requirement_decision(
        run_complexity_scale_workbench_benchmark.PROMPT,
        run_dir,
    )
    run_complexity_scale_workbench_benchmark.discovery_selection_lane.run_discovery_selection(
        run_complexity_scale_workbench_benchmark.PROMPT,
        run_dir / "discovery",
    )
    project_dir.mkdir()

    acceptance = run_complexity_scale_workbench_benchmark.evaluate(project_dir, run_dir, {"status": "skipped"}, {"returncode": None})

    assert acceptance["requirement_decision_status"] == "PASS"
    assert acceptance["product_contract_status"] != "PASS"
    assert acceptance["implementation_status"] != "PASS"
    assert acceptance["delivery_status"] != "PASS"
    assert acceptance["checks"]["planning_contract_gate"]["status"] != "PASS"
    assert "product_brief.md_missing" in acceptance["checks"]["planning_contract_gate"]["missing"]
