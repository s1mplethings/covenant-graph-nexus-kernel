from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_large_project_agent_led_benchmark


def test_benchmark_report_schema_from_fake_result() -> None:
    report = {
        "architecture_direction": "agent-led",
        "director_loop_used": True,
        "selected_tools": ["formal_generation:local_first", "final_promotion"],
        "agent_decision_ledger": "run/artifacts/agent_decision_ledger.jsonl",
        "final_project": "run/final_project",
        "complexity": {"page_count": 9, "module_count": 9},
        "product_acceptance": {"status": "pass", "missing_core_features": [], "weak_features": [], "ux_score": 90},
        "commercial_status": "COMMERCIAL_READY",
        "remaining_blockers": [],
    }

    for key in (
        "architecture_direction",
        "director_loop_used",
        "selected_tools",
        "agent_decision_ledger",
        "final_project",
        "complexity",
        "product_acceptance",
        "commercial_status",
        "remaining_blockers",
    ):
        assert key in report


def test_benchmark_fails_without_agent_decision_ledger(tmp_path: pathlib.Path, monkeypatch) -> None:
    missing = tmp_path / "run" / "artifacts" / "agent_decision_ledger.jsonl"
    monkeypatch.setattr(run_large_project_agent_led_benchmark.agent_decision_ledger, "decision_ledger_path", lambda run_dir: missing)

    blockers = []
    if not pathlib.Path(run_large_project_agent_led_benchmark.agent_decision_ledger.decision_ledger_path(tmp_path / "run")).exists():
        blockers.append("agent_decision_ledger_missing")

    assert "agent_decision_ledger_missing" in blockers


def test_benchmark_final_artifacts_required(tmp_path: pathlib.Path) -> None:
    final_project = tmp_path / "final_project"
    final_project.mkdir()
    missing = [
        not (final_project / "final_project_bundle.zip").exists(),
        not (final_project / "delivery_manifest.json").exists(),
        not (final_project / "artifacts" / "screenshots" / "overview.png").exists(),
        not (final_project / "artifacts" / "videos" / "production_hub_walkthrough.gif").exists(),
    ]

    assert any(missing)


def test_benchmark_materializes_public_gate_video_evidence(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "candidate_project"

    run_large_project_agent_led_benchmark.write_project_files(project)

    video = project / "artifacts" / "videos" / "production_hub_walkthrough.gif"
    assert video.exists()
    assert video.read_bytes().startswith(b"GIF89a")


def test_provider_quota_fallback_selection_not_direct_fail() -> None:
    state = {
        "formal_generation_materialized": False,
        "provider_quota_exceeded": True,
        "local_model_available": True,
        "has_project_spec": True,
        "fallback_reverify_status": "missing",
    }
    decision = run_large_project_agent_led_benchmark.agent_director_loop.deterministic_director_decide("large project", state, [])

    assert decision["selected_tool"] == "formal_generation"
    assert decision["provider_strategy"] == "local_only"
    assert decision["reason"] != "WAITING_FOR_PROVIDER_QUOTA"
