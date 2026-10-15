from __future__ import annotations

import pathlib
import time

from scripts import run_real_workload_recovery_stress as stress


def valid_summary() -> dict:
    resources = {field: {"min": 0, "max": 1, "mean": 0.5, "first": 0, "last": 1, "delta": 1} for field in stress.REQUIRED_RESOURCE_FIELDS}
    resources.update({
        "sample_count": 2,
        "active_sample_count": 2,
        "requested_interval_seconds": 0.1,
        "observed_interval_seconds": {"p50": 0.1, "p95": 0.1, "p99": 0.1, "max": 0.1},
        "disk_refresh_interval_seconds": 5.0,
    })
    return {
        "faults": {"observations": {name: True for name in stress.REQUIRED_FAULTS}},
        "profiles": [
            {
                "configuration": {"requested_duration_seconds": 1.0, "arrival_rate_per_second": 2.0},
                "accounting": {
                    "planned": 3,
                    "submitted": 2,
                    "rejected": 1,
                    "cancelled": 0,
                    "timed_out": 0,
                    "failed": 0,
                    "completed": 2,
                    "independent_acceptance_passed": 2,
                },
                "elapsed_seconds": 1.0,
                "resources": resources,
                "resource_stability_limits": {"max_handle_growth": 64, "max_rss_growth_bytes": 134217728, "minimum_samples": 2, "max_sample_gap_seconds": 10},
            }
        ],
    }


def test_evidence_validator_rejects_partial_completion_and_missing_fault() -> None:
    candidate = valid_summary()
    candidate["faults"]["observations"]["worker_kill"] = False
    candidate["profiles"][0]["accounting"]["completed"] = 1
    verdict = stress.validate_evidence(candidate)
    assert verdict["status"] == "FAIL"
    assert "fault_not_observed:worker_kill" in verdict["errors"]
    assert "profile_0:denominator_unbalanced" in verdict["errors"]


def test_evidence_validator_rejects_missing_resources_and_short_duration() -> None:
    candidate = valid_summary()
    candidate["profiles"][0]["resources"]["rss_bytes"]["max"] = None
    candidate["profiles"][0]["elapsed_seconds"] = 0.1
    verdict = stress.validate_evidence(candidate)
    assert verdict["status"] == "FAIL"
    assert "profile_0:resource_missing:rss_bytes" in verdict["errors"]
    assert "profile_0:duration_short" in verdict["errors"]


def test_evidence_validator_rejects_unbounded_handle_growth() -> None:
    candidate = valid_summary()
    candidate["profiles"][0]["resources"]["handle_count"]["delta"] = 65
    verdict = stress.validate_evidence(candidate)
    assert verdict["status"] == "FAIL"
    assert "profile_0:handle_growth_unbounded" in verdict["errors"]


def test_evidence_validator_rejects_sparse_resource_sampling() -> None:
    candidate = valid_summary()
    candidate["profiles"][0]["resource_stability_limits"]["minimum_samples"] = 3
    candidate["profiles"][0]["resources"]["observed_interval_seconds"]["max"] = 11
    verdict = stress.validate_evidence(candidate)
    assert verdict["status"] == "FAIL"
    assert "profile_0:resource_samples_missing" in verdict["errors"]
    assert "profile_0:resource_sample_gap_exceeded" in verdict["errors"]


def test_evidence_validator_accepts_complete_accounted_profile() -> None:
    assert stress.validate_evidence(valid_summary()) == {"status": "PASS", "errors": []}


def test_real_fault_suite_uses_process_and_canonical_checkpoint_recovery(tmp_path: pathlib.Path) -> None:
    report = stress.run_fault_suite(tmp_path)
    assert report["status"] == "PASS"
    assert report["observations"] == {name: True for name in stress.REQUIRED_FAULTS}
    assert report["details"]["worker_kill"]["alive_before"] is True
    assert report["details"]["worker_kill"]["dead_after"] is True
    assert report["details"]["corrupt_checkpoint_recovery"]["recovery_provider_calls"] >= 1


def test_fixed_arrival_profile_records_complete_telemetry(tmp_path: pathlib.Path) -> None:
    report = stress.run_fixed_arrival_profile(
        tmp_path,
        project_concurrency=2,
        provider_job_concurrency=2,
        arrival_rate=4.0,
        duration_seconds=0.6,
        sample_interval=0.05,
    )
    assert report["status"] == "PASS"
    assert report["denominator_balanced"] is True
    assert report["latency_seconds"]["p50"] is not None
    assert report["latency_seconds"]["p95"] is not None
    assert report["latency_seconds"]["p99"] is not None
    assert report["resources"]["sample_count"] >= 2
    assert report["gates"]["resource_stability"] == "PASS"
    assert (tmp_path / "arrival_events.jsonl").is_file()
    assert (tmp_path / "resource_events.jsonl").is_file()


def test_fixed_arrival_reaps_terminal_events_during_arrival_window(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    def quick_project(*_args, **_kwargs):
        time.sleep(0.05)
        return {"accepted": True, "acceptance": {"status": "PASS"}, "files": 1}

    monkeypatch.setattr(stress, "execute_project", quick_project)
    report = stress.run_fixed_arrival_profile(
        tmp_path,
        project_concurrency=2,
        provider_job_concurrency=2,
        arrival_rate=1.0,
        duration_seconds=2.1,
        sample_interval=0.05,
    )
    events = [line for line in (tmp_path / "arrival_events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    terminal_index = next(index for index, line in enumerate(events) if '"event":"completed"' in line)
    last_planned_index = max(index for index, line in enumerate(events) if '"event":"planned"' in line)
    assert terminal_index < last_planned_index
    assert report["latency_seconds"]["p99"] < 0.5
