from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import run_pass6_latency_audit as audit
from scripts import run_real_workload_recovery_stress as stress


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_incremental_sampler_accounts_completed_projects_without_live_recursive_thread(tmp_path: Path) -> None:
    run = tmp_path / "run"
    project = run / "projects" / "project-000000"
    (project / "provider_components").mkdir(parents=True)
    (project / "provider_components" / "checkpoint.json").write_text("{}", encoding="utf-8")
    (project / "result.json").write_text("{}", encoding="utf-8")
    sampler = stress.ResourceSampler(run, lambda: {}, interval=0.05, filesystem_mode="incremental")
    assert sampler._disk_thread is None
    sampler.record_completed_project(project)
    sampler.record_completed_project(project)
    assert sampler._filesystem_metrics["artifact_count"] == 2
    assert sampler._filesystem_metrics["checkpoint_count"] >= 1


def test_legacy_sampler_records_recursive_scan_windows(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence.json").write_text("{}", encoding="utf-8")
    sampler = stress.ResourceSampler(run, lambda: {}, interval=0.05, filesystem_mode="legacy_recursive")
    sampler._disk_refresh_interval = 0.05
    sampler.start()
    sampler._stop.wait(0.12)
    sampler.stop()
    scans = audit._read_jsonl(run / "filesystem_scan_events.jsonl")
    assert scans
    assert all(row["mode"] == "legacy_recursive" for row in scans)
    assert all(row["duration_seconds"] >= 0 for row in scans)


def test_midterm_window_keeps_original_latency_gate(tmp_path: Path) -> None:
    started = datetime.now(timezone.utc)
    run = tmp_path / "midterm-test"
    events = []
    for index, latency in enumerate((0.10, 0.11, 0.12, 0.20, 0.21, 0.22)):
        offset = index * 3600
        at = started + timedelta(seconds=offset)
        events.extend([
            {"at": at.isoformat(), "event": "submitted", "task_id": f"project-{index:06d}", "submission_lag_seconds": 0.0},
            {"at": at.isoformat(), "event": "completed", "task_id": f"project-{index:06d}", "latency_seconds": latency, "accepted": True},
        ])
    _write_jsonl(run / "SOAK_EVENTS.jsonl", events)
    (run / "profile_summary.json").write_text(json.dumps({
        "elapsed_seconds": 18000,
        "accounting": {
            "planned": 6,
            "rejected": 0,
            "cancelled": 0,
            "timed_out": 0,
            "failed": 0,
            "completed": 6,
            "independent_acceptance_passed": 6,
            "independent_acceptance_failed": 0,
        },
        "gates": {"resource_stability": "PASS"},
    }), encoding="utf-8")
    result = audit._window_validation(run, minimum_duration=14400)
    assert result["status"] == "FAIL"
    assert result["gates"]["last_2h_latency"] is False
    assert result["gate_limit"] == 1.15


def test_phase_profiler_exposes_all_requested_phase_names(tmp_path: Path) -> None:
    output = tmp_path / "profile"
    result = audit._experiment_profile(
        output,
        mode="incremental",
        retained_roots=[],
        task_count=2,
        arrival_rate=1.0,
    )
    expected = {
        "leaf_work_graph_build",
        "cache_scan",
        "batch_scheduling",
        "emission_planning",
        "context_preflight",
        "deterministic_provider_free_execution",
        "owned_file_verification",
        "interface_publication",
        "boundary_receipt_creation",
        "artifact_evidence_write",
        "independent_acceptance",
    }
    assert expected <= set(result["phase_timing"])
    assert result["status"] == "PASS"
