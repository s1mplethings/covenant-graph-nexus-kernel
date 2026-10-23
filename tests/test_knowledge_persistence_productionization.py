from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_persistence_productionization import runner
from cgnk_knowledge import PersistencePolicy


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
