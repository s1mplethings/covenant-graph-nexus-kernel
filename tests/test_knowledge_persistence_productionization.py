from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.knowledge_persistence_productionization import runner
from benchmarks.knowledge_persistence_productionization import resource_policy
from cgnk_knowledge import PersistencePolicy, save_project_knowledge


def test_production_benchmark_uses_versioned_policy_and_foundation() -> None:
    args = runner.parser().parse_args([])
    policy = PersistencePolicy()

    assert args.checkpoint_interval == policy.checkpoint_mutation_interval == 256
    assert args.checkpoint_tail_bytes == policy.checkpoint_tail_bytes == 64 * 1024 * 1024
    assert args.compaction_threshold == policy.compaction_segment_threshold == 64
    assert args.compaction_batch == policy.compaction_batch_size == 32
    assert runner.foundation.benchmark_hashes() == runner.foundation.benchmark_hashes()


def test_scale_worker_exercises_production_backend(tmp_path: Path) -> None:
    result_path = tmp_path / "scale.json"
    exit_code = runner.main([
        "--worker", "scale",
        "--size", "100",
        "--store-root", str(tmp_path / "pack"),
        "--result-path", str(result_path),
        "--update-samples", "2",
        "--checkpoint-interval", "4",
        "--checkpoint-tail-bytes", str(1024 * 1024 * 1024),
        "--compaction-threshold", "4",
        "--compaction-batch", "2",
        "--worker-timeout", "120",
    ])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["provider_calls"] == 0
    assert result["single_local_update"]["samples"] == 2
    assert result["compaction"]["full_replay_semantic_equivalence"] is True
    assert set(result["cold_start"]) == {"full_replay", "valid_checkpoint", "corrupt_checkpoint"}
    assert all(row["status"] == "PASS" for row in result["cold_start"].values())
    assert result["maintenance_signals"] == {
        "checkpoint_due_observed": True,
        "compaction_due_observed": True,
    }


def test_crash_worker_recovers_old_or_new_committed_state(tmp_path: Path) -> None:
    result_path = tmp_path / "crash.json"
    exit_code = runner.main([
        "--worker", "crash",
        "--size", "100",
        "--store-root", str(tmp_path / "pack"),
        "--result-path", str(result_path),
    ])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result["status"] == "PASS"
    assert len(result["crash_points"]) == 6
    assert all(not row["silent_corruption"] for row in result["crash_points"])


def test_restart_superseding_update_is_visible_without_losing_history(tmp_path: Path) -> None:
    root = tmp_path / "pack"
    policy = PersistencePolicy()
    pack = runner.foundation.generate_corpus(100, 20, "uniform")
    save_project_knowledge(root, pack, format_version="2.0", policy=policy)

    result = runner._restart_superseding_visibility(root, size=100, branches=20, policy=policy)

    assert result["status"] == "PASS"
    assert result["relation"] == "SUPERSEDING"
    assert all(result["checks"].values())
    assert "pack" not in result["write"]
    assert len(json.dumps(result)) < 20_000


def test_workload_worker_measures_query_conversation_and_disk(tmp_path: Path) -> None:
    result_path = tmp_path / "workload.json"
    exit_code = runner.main([
        "--worker", "workload", "--size", "100",
        "--store-root", str(tmp_path / "pack"), "--result-path", str(result_path),
        "--operations", "12",
    ])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["disk_footprint"]["observed_active_peak_bytes"] > 0
    assert all(row["conversation_failures"] == 0 for row in result["workloads"])
    assert all("p99" in row["conversation_ms"] for row in result["workloads"])
    assert all("p99" in row["retrieval_ms"] for row in result["workloads"])


def _calibrations() -> list[dict[str, int | str]]:
    return [
        {
            "scale": 1_000, "measurement_status": "COMPLETE",
            "initial_authoritative_bytes": 3_000_000, "checkpoint_bytes": 3_300_000,
            "largest_update_segment_bytes": 4_000, "compaction_bytes_written": 90_000,
            "peak_manifest_bytes": 30_000, "observed_active_peak_bytes": 7_000_000,
            "baseline_rss_bytes": 50_000_000, "peak_rss_bytes": 75_000_000,
        },
        {
            "scale": 5_000, "measurement_status": "COMPLETE",
            "initial_authoritative_bytes": 14_000_000, "checkpoint_bytes": 15_000_000,
            "largest_update_segment_bytes": 4_200, "compaction_bytes_written": 92_000,
            "peak_manifest_bytes": 32_000, "observed_active_peak_bytes": 30_000_000,
            "baseline_rss_bytes": 50_000_000, "peak_rss_bytes": 130_000_000,
        },
    ]


def _estimate(*, disk: int = 2 * resource_policy.GIB, memory: int = 2 * resource_policy.GIB) -> dict[str, int]:
    return {"conservative_peak_bytes": disk, "predicted_process_peak_rss_bytes": memory}


def test_resource_gate_allows_high_used_percent_with_large_absolute_headroom() -> None:
    result = resource_policy.evaluate_resource_gate(
        volume_total_bytes=2_000 * resource_policy.GIB,
        volume_free_bytes=300 * resource_policy.GIB,
        memory_total_bytes=32 * resource_policy.GIB,
        memory_available_bytes=16 * resource_policy.GIB,
        estimate=_estimate(),
    )

    assert result["status"] == "PASS"
    assert result["predicted_post_run"]["used_percent"] > 75


def test_resource_gate_rejects_low_used_percent_with_insufficient_absolute_capacity() -> None:
    result = resource_policy.evaluate_resource_gate(
        volume_total_bytes=10 * resource_policy.GIB,
        volume_free_bytes=9 * resource_policy.GIB,
        memory_total_bytes=32 * resource_policy.GIB,
        memory_available_bytes=16 * resource_policy.GIB,
        estimate=_estimate(),
    )

    assert result["status"] == "FAIL"
    assert "ABSOLUTE_DISK_HEADROOM_INSUFFICIENT" in result["reasons"]


def test_peak_estimator_includes_checkpoint_compaction_and_transaction_duplicates() -> None:
    estimate = resource_policy.estimate_peak_resources(scale=250_000, calibrations=_calibrations())
    components = estimate["components"]

    assert components["checkpoint_upper_bytes"] > 0
    assert components["compaction_duplicate_bytes"] >= 92_000
    assert components["transaction_or_rollback_duplicate_bytes"] >= components["compaction_duplicate_bytes"]
    assert estimate["conservative_peak_bytes"] > estimate["expected_peak_bytes"] > estimate["lower_bound_bytes"]


def test_resource_gate_enforces_os_and_benchmark_reserve() -> None:
    estimate = _estimate()
    result = resource_policy.evaluate_resource_gate(
        volume_total_bytes=2_000 * resource_policy.GIB,
        volume_free_bytes=19 * resource_policy.GIB,
        memory_total_bytes=32 * resource_policy.GIB,
        memory_available_bytes=16 * resource_policy.GIB,
        estimate=estimate,
    )

    assert result["status"] == "FAIL"
    assert result["thresholds"]["required_free_bytes"] > 19 * resource_policy.GIB


def test_resource_gate_enforces_memory_headroom() -> None:
    result = resource_policy.evaluate_resource_gate(
        volume_total_bytes=2_000 * resource_policy.GIB,
        volume_free_bytes=300 * resource_policy.GIB,
        memory_total_bytes=32 * resource_policy.GIB,
        memory_available_bytes=3 * resource_policy.GIB,
        estimate=_estimate(memory=2 * resource_policy.GIB),
    )

    assert result["status"] == "FAIL"
    assert "ABSOLUTE_MEMORY_HEADROOM_INSUFFICIENT" in result["reasons"]


def test_peak_estimator_fails_closed_on_uncertain_calibration() -> None:
    rows = _calibrations()
    rows[1]["measurement_status"] = "INCOMPLETE"

    with pytest.raises(ValueError, match="RESOURCE_CALIBRATION_UNCERTAIN"):
        resource_policy.estimate_peak_resources(scale=250_000, calibrations=rows)


def test_resource_gate_fails_closed_when_metrics_are_missing() -> None:
    result = resource_policy.evaluate_resource_gate(
        volume_total_bytes=None,
        volume_free_bytes=300 * resource_policy.GIB,
        memory_total_bytes=32 * resource_policy.GIB,
        memory_available_bytes=16 * resource_policy.GIB,
        estimate=_estimate(),
    )

    assert result["status"] == "FAIL"
    assert result["reasons"] == ["RESOURCE_METRIC_UNAVAILABLE: volume_total_bytes"]


def test_resource_gate_secondary_guard_rejects_predicted_nearly_full_volume() -> None:
    result = resource_policy.evaluate_resource_gate(
        volume_total_bytes=10_000 * resource_policy.GIB,
        volume_free_bytes=250 * resource_policy.GIB,
        memory_total_bytes=32 * resource_policy.GIB,
        memory_available_bytes=16 * resource_policy.GIB,
        estimate=_estimate(disk=60 * resource_policy.GIB),
    )

    assert result["status"] == "FAIL"
    assert "PREDICTED_VOLUME_NEARLY_FULL" in result["reasons"]
