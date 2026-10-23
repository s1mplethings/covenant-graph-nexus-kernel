from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / "benchmarks" / "knowledge_persistence_scaling" / "runner.py"
SPEC = importlib.util.spec_from_file_location("knowledge_persistence_scaling_runner", PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def test_realistic_corpus_contains_required_lifecycle_shapes() -> None:
    pack = runner.generate_corpus(1_000, 20, "uniform")
    counts = runner.corpus_counts(pack)
    assert counts["items"] == 1_000
    assert counts["derived_items"] > 0
    assert counts["stale_items"] > 0
    assert counts["superseded_items"] > 0
    assert counts["retracted_items"] > 0
    assert counts["contradiction_items"] > 0
    assert counts["multi_source_items"] > 0
    assert pack["knowledge_index"]["item_count"] == 1_000


def test_query_set_preserves_recall_and_filters_lifecycle_state() -> None:
    pack = runner.generate_corpus(1_000, 20, "hot_branch_skew")
    result = runner.evaluate_queries(pack, runner.query_cases(1_000, 20, "hot_branch_skew"), repeats=1)
    assert result["recall_pass"] is True
    assert result["accuracy"] == 1.0
    by_name = {row["name"]: row for row in result["cases"]}
    assert "ki-000000" not in by_name["superseded_fact"]["selected_ids"]
    assert "ki-000009" not in by_name["stale_summary_raw_fallback"]["selected_ids"]
    assert by_name["no_evidence"]["selected_ids"] == []


def test_real_filesystem_save_and_load_components_are_equivalent() -> None:
    pack = runner.generate_corpus(200, 20, "long_tail")
    expected = runner.stable_hash(runner.authoritative_projection(pack))
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "knowledge.json"
        saved, save_metrics = runner.measure_save(pack, path)
        loaded, load_metrics = runner._load_components(path)
    assert save_metrics["file_bytes"] > 0
    assert save_metrics["serialized_bytes"] <= save_metrics["file_bytes"]
    assert save_metrics["physical_written_bytes"] == save_metrics["file_bytes"]
    assert load_metrics["total_cold_load_ms"] >= 0
    assert runner.stable_hash(runner.authoritative_projection(saved)) == expected
    assert runner.stable_hash(runner.authoritative_projection(loaded)) == expected


def test_single_update_exposes_physical_write_amplification_without_global_recompute() -> None:
    pack = runner.generate_corpus(200, 20, "uniform")
    with tempfile.TemporaryDirectory() as tmp:
        updated, metrics = runner._single_update_series(pack, pathlib.Path(tmp) / "knowledge.json", 2)
    assert len(updated["all_items"]) == 202
    assert metrics["persistence_write_amplification"]["p50"] > 1
    assert all(row["recomputed_nodes"] == 0 for row in metrics["receipts"])
    assert all(row["unrelated_nodes_touched"] == 0 for row in metrics["receipts"])


def test_benchmark_hashes_and_crash_safety_are_deterministic() -> None:
    first = runner.benchmark_hashes()
    second = runner.benchmark_hashes()
    assert first == second
    assert set(first) == {
        "corpus_generator_hash", "corpus_shape_hash", "queryset_hash", "workload_hash",
        "persistence_policy_hash", "retrieval_policy_hash", "context_policy_hash", "model_config_hash",
    }
    with tempfile.TemporaryDirectory() as tmp:
        result = runner.crash_safety_probe(pathlib.Path(tmp))
    assert result["partial_json_detected"] is True
    assert result["partial_write_recovery"] is False
    assert result["corrupt_derived_index_rebuilt"] is True
    assert result["valid_json_tamper_detected"] is False


def test_worker_output_is_json_serializable() -> None:
    value = {
        "hashes": runner.benchmark_hashes(),
        "shape": runner.SHAPE_SPEC,
        "workload": runner.WORKLOAD_SPEC,
    }
    assert json.loads(json.dumps(value))["shape"] == runner.SHAPE_SPEC
