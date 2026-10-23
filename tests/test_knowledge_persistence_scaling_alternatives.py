from __future__ import annotations

import pathlib
import tempfile

from benchmarks.knowledge_persistence_scaling import alternatives, runner


def test_alternative_stores_round_trip_same_logical_authority() -> None:
    pack = runner.generate_corpus(200, 20, "uniform")
    expected = runner.stable_hash(runner.authoritative_projection(pack))
    for strategy in alternatives.STRATEGIES:
        with tempfile.TemporaryDirectory() as tmp:
            store = alternatives.store_for(strategy, pathlib.Path(tmp))
            metrics = store.initialize(pack)
            loaded = store.load()
            if isinstance(loaded, tuple):
                loaded = loaded[0]
            assert metrics["bytes_written"] > 0
            assert runner.stable_hash(runner.authoritative_projection(loaded)) == expected


def test_alternative_update_preserves_semantics_and_is_queryable() -> None:
    original = runner.generate_corpus(200, 20, "uniform")
    for strategy in alternatives.STRATEGIES:
        pack = runner.rebuild_pack_indexes(dict(original))
        with tempfile.TemporaryDirectory() as tmp:
            store = alternatives.store_for(strategy, pathlib.Path(tmp))
            store.initialize(pack)
            result = alternatives.internalize_evidence(
                pack, runner._update_evidence(999, "branch-0001"),
                policy=alternatives.KnowledgeMaintenancePolicy.LOCAL_LAZY,
            )
            pack = result["pack"]
            changed = [result["receipt"]["evidence_id"], *result["receipt"]["nodes_invalidated"]]
            store.persist(pack, "branch-0001", changed)
            loaded = store.load()
            if isinstance(loaded, tuple):
                loaded = loaded[0]
            assert runner.stable_hash(runner.authoritative_projection(loaded)) == runner.stable_hash(runner.authoritative_projection(pack))
            assert loaded["knowledge_index"]["item_count"] == 201


def test_alternative_crash_probes_fail_closed_or_rebuild_derived_data() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = alternatives.crash_probes(pathlib.Path(tmp))
    assert result["S1_CHUNKED"]["corrupt_chunk_detected"] is True
    assert result["S1_CHUNKED"]["unreferenced_temp_ignored"] is True
    assert result["S2_APPEND_LOG"]["incomplete_tail_recovered"] is True
    assert result["S2_APPEND_LOG"]["corrupt_checkpoint_discarded"] is True
    assert result["S3_AUTHORITY_SIDECAR"]["corrupt_sidecar_rebuilt"] is True
    assert result["S3_AUTHORITY_SIDECAR"]["interrupted_temp_preserves_authority"] is True
