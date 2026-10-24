from __future__ import annotations

from cgkn.application.self_growth import GrowthGroup
from experiments.self_growth_v1.cases import ordered_task_stream
from experiments.self_growth_v1.runner import GrowthBenchmarkRunner, StaticCandidateBackend


def run_group(tmp_path, group):
    return GrowthBenchmarkRunner(group, StaticCandidateBackend(), tmp_path / group.name).run()


def test_g0_frozen_registry_exposes_real_coverage_gap(tmp_path) -> None:
    receipt = run_group(tmp_path, GrowthGroup.G0)
    metrics = receipt["metrics"]
    assert metrics["new_capabilities_created"] == 0
    assert receipt["final_experimental_registry_size"] == receipt["production_registry_size"] == 10
    assert metrics["critical_stop_correctness"] == 1.0
    assert receipt["production_registry_modified"] is False
    assert metrics["successes"] < 100


def test_g1_naive_growth_succeeds_with_capability_explosion(tmp_path) -> None:
    receipt = run_group(tmp_path, GrowthGroup.G1)
    metrics = receipt["metrics"]
    assert metrics["successes"] == 83
    assert metrics["new_capabilities_created"] == 58
    assert metrics["duplicate_capability_count"] == 17
    assert metrics["false_gap_rate"] == 0.6
    assert receipt["final_experimental_registry_size"] == 68


def test_g2_search_compose_create_internalizes_families(tmp_path) -> None:
    receipt = run_group(tmp_path, GrowthGroup.G2)
    metrics = receipt["metrics"]
    assert metrics["successes"] == 100
    assert metrics["new_capabilities_created"] == 15
    assert metrics["true_gap_precision"] == metrics["true_gap_recall"] == 1.0
    assert metrics["capability_internalization_rate"] == 1.0
    assert metrics["zero_reuse_capability_rate"] == 0.0
    assert receipt["final_experimental_registry_size"] == 25
    assert receipt["windows"][-1]["new_capability_rate"] == 0.0


def test_g3_uses_strong_only_for_ambiguous_growth_decisions(tmp_path) -> None:
    receipt = run_group(tmp_path, GrowthGroup.G3)
    assert receipt["metrics"]["successes"] == 100
    assert len(receipt["strong_context_packets"]) == 8
    assert all(row["reduction_ratio"] > 0 for row in receipt["strong_context_packets"])
    assert receipt["metrics"]["new_capabilities_created"] == 15


def test_all_groups_use_identical_stream_and_independent_registries(tmp_path) -> None:
    receipts = [run_group(tmp_path, group) for group in GrowthGroup]
    hashes = {row["benchmark_hashes"]["task_stream_hash"] for row in receipts}
    assert len(hashes) == 1
    assert len(ordered_task_stream()) == 100
    assert [row["production_registry_size"] for row in receipts] == [10, 10, 10, 10]
    assert [row["final_experimental_registry_size"] for row in receipts] == [10, 68, 25, 25]
