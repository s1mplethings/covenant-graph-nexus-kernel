from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgkn.application.conversation import ConversationRequest, ConversationService  # noqa: E402
from cgnk_knowledge import (  # noqa: E402
    KnowledgePersistenceError,
    PersistencePolicy,
    SegmentedKnowledgeStore,
    internalize_evidence,
    load_project_knowledge,
    make_derived_abstraction,
    migrate_legacy_pack,
    new_project_knowledge_pack,
    project_knowledge_semantic_hash,
    retrieve_relevant_knowledge,
    rollback_legacy_migration,
    save_legacy_project_knowledge,
    save_project_knowledge,
    upsert_knowledge_items,
)
from cgnk_knowledge.persistence import (  # noqa: E402
    _WriteLock,
    _document_bytes,
    _finalize_manifest,
    _json_bytes,
    _read_document,
    _sha256,
)


def evidence(content: str, **overrides) -> dict:
    value = {
        "content": content,
        "item_type": "research_finding",
        "scope": "project",
        "source_ref": "source:fixture",
        "subject_ref": "service.port",
        "branch_ref": "service",
        "source_version": "1",
        "importance": "high",
        "need_state": "needed_now",
    }
    value.update(overrides)
    return value


def append(pack: dict, path: pathlib.Path, value: dict) -> tuple[dict, dict]:
    result = internalize_evidence(pack, value)
    write = save_project_knowledge(path, result["pack"], mutation=result["persistence_mutation"])
    return result["pack"], write


def create_store(tmp_path: pathlib.Path, *, policy: PersistencePolicy | None = None) -> tuple[pathlib.Path, dict]:
    path = tmp_path / "knowledge.pack"
    pack = new_project_knowledge_pack("fixture", "pkp_fixture")
    save_project_knowledge(path, pack, format_version="2.0", policy=policy or PersistencePolicy())
    return path, load_project_knowledge(path)


def manifest_payload(path: pathlib.Path) -> dict:
    return _read_document(path / "manifest.json", 32 * 1024 * 1024)[0]


def write_manifest(path: pathlib.Path, manifest: dict) -> None:
    value = _finalize_manifest(manifest)
    (path / "manifest.json").write_bytes(_document_bytes(value))


def fail_at(point: str):
    def inject(actual: str) -> None:
        if actual == point:
            raise RuntimeError(point)

    return inject


def test_new_v2_empty_pack_is_explicit_and_round_trips(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    assert path.is_dir()
    assert manifest_payload(path)["format_version"] == "2.0"
    assert pack["all_items"] == []
    assert SegmentedKnowledgeStore(path).verify()["status"] == "PASS"


def test_new_pack_retains_legacy_default_until_adoption_gate(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "knowledge.json"
    pack = new_project_knowledge_pack("fixture", "pkp_legacy_default")

    result = save_project_knowledge(path, pack)

    assert path.is_file()
    assert result["kind"] == "KnowledgeStoreWriteResult"
    assert load_project_knowledge(path)["id"] == "pkp_legacy_default"


def test_single_append_is_bounded_and_visible(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    pack, write = append(pack, path, evidence("Port is 8000."))
    assert write["sequence_start"] == write["sequence_end"] == 2
    assert write["authoritative_bytes_written"] < 16_000
    assert load_project_knowledge(path)["all_items"][0]["content"] == "Port is 8000."


def test_one_hundred_sequential_mutations_have_strict_sequences(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    for index in range(100):
        pack, _ = append(
            pack, path,
            evidence(f"Fact {index}", subject_ref=f"subject.{index}", branch_ref=f"branch.{index}", source_version=str(index + 1)),
        )
    manifest = manifest_payload(path)
    assert manifest["latest_sequence"] == 101
    assert len(manifest["authoritative_segments"]) == 101
    assert len(load_project_knowledge(path)["all_items"]) == 100


@pytest.mark.parametrize(
    ("relation", "content", "overrides"),
    [
        ("SUPERSEDING", "Port is 9000.", {"source_ref": "source:2", "source_version": "2"}),
        ("CONTRADICTING", "Port is not 8000.", {"source_ref": "source:2", "relation": "CONTRADICTING", "target_id": "DYNAMIC"}),
        ("CORRECTION", "Port is 8080.", {"source_ref": "source:2", "relation": "CORRECTION", "target_id": "DYNAMIC"}),
        ("RETRACTION", "Retract port evidence.", {"source_ref": "source:2", "relation": "RETRACTION", "target_id": "DYNAMIC"}),
    ],
)
def test_relation_history_survives_restart(tmp_path: pathlib.Path, relation: str, content: str, overrides: dict) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    old_id = pack["all_items"][0]["id"]
    update = dict(overrides)
    if update.get("target_id") == "DYNAMIC":
        update["target_id"] = old_id
    pack, _ = append(pack, path, evidence(content, **update))
    loaded = load_project_knowledge(path)
    by_id = {row["id"]: row for row in loaded["all_items"]}
    assert len(by_id) == 2
    assert loaded._persistence_sequence == 3
    if relation in {"SUPERSEDING", "CORRECTION"}:
        assert by_id[old_id]["status"] == "superseded"
    elif relation == "RETRACTION":
        assert by_id[old_id]["status"] == "retracted"
    else:
        assert by_id[old_id]["review_state"] == "conflict"


def test_duplicate_ingestion_persists_merged_provenance(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    pack, write = append(pack, path, evidence("Port is 8000.", source_ref="source:second"))
    assert write["sequence_end"] == 3
    loaded = load_project_knowledge(path)
    assert loaded["all_items"][0]["source_refs"] == ["source:fixture", "source:second"]
    assert loaded["all_items"][0]["observation_count"] == 2


def test_stale_derived_invalidation_persists(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    raw_id = pack["all_items"][0]["id"]
    derived = make_derived_abstraction("summary.port", "Port summary.", [raw_id], branch_ref="service")
    pack = upsert_knowledge_items(pack, [derived])
    save_project_knowledge(path, pack)
    pack, _ = append(pack, path, evidence("Port is 9000.", source_ref="source:2", source_version="2"))
    loaded = load_project_knowledge(path)
    stale = next(row for row in loaded["all_items"] if row["id"] == "summary.port")
    assert stale["derived_state"] == "stale"
    assert "summary.port" not in {row["id"] for row in retrieve_relevant_knowledge(loaded, {"goal": "Port summary", "require_relevance": True})["selected_items"]}


def test_checkpoint_creation_and_valid_load(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    receipt = SegmentedKnowledgeStore(path).create_checkpoint()
    loaded = load_project_knowledge(path)
    assert receipt["status"] == "PASS"
    assert loaded._load_receipt["checkpoint_status"] == "VALID_USED"
    assert project_knowledge_semantic_hash(pack) == project_knowledge_semantic_hash(loaded)


@pytest.mark.parametrize("mode", ["corrupt", "missing", "authority_mismatch", "index_missing"])
def test_invalid_checkpoint_is_rejected_and_authority_replayed(tmp_path: pathlib.Path, mode: str) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    store = SegmentedKnowledgeStore(path)
    store.create_checkpoint()
    manifest = manifest_payload(path)
    checkpoint = path / manifest["current_checkpoint"]["path"]
    if mode == "corrupt":
        checkpoint.write_bytes(b"{broken")
    elif mode == "missing":
        checkpoint.unlink()
    else:
        payload, _ = _read_document(checkpoint, 1024 * 1024 * 1024)
        if mode == "authority_mismatch":
            payload["authority_root_hash"] = "sha256:" + "f" * 64
        else:
            payload.pop("knowledge_index")
        raw = _document_bytes(payload)
        checkpoint.write_bytes(raw)
        manifest["current_checkpoint"]["file_hash"] = _sha256(raw)
        manifest["current_checkpoint"]["file_bytes"] = len(raw)
        write_manifest(path, manifest)
    loaded = store.load()
    assert loaded._load_receipt["checkpoint_status"].startswith("REJECTED_REPLAYED")
    assert project_knowledge_semantic_hash(loaded) == project_knowledge_semantic_hash(pack)


def test_tail_replay_after_checkpoint(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    SegmentedKnowledgeStore(path).create_checkpoint()
    pack = load_project_knowledge(path)
    pack, _ = append(pack, path, evidence("Retry twice.", subject_ref="retry", branch_ref="retry"))
    loaded = load_project_knowledge(path)
    assert loaded._load_receipt["checkpoint_status"] == "VALID_USED"
    assert {row["content"] for row in loaded["all_items"]} == {"Port is 8000.", "Retry twice."}


@pytest.mark.parametrize("failure", ["checksum", "missing", "partial"])
def test_referenced_segment_damage_fails_closed(tmp_path: pathlib.Path, failure: str) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    manifest = manifest_payload(path)
    segment = path / manifest["authoritative_segments"][-1]["path"]
    if failure == "missing":
        segment.unlink()
    elif failure == "partial":
        raw = segment.read_bytes()
        segment.write_bytes(raw[: len(raw) // 2])
    else:
        raw = bytearray(segment.read_bytes())
        raw[len(raw) // 2] ^= 1
        segment.write_bytes(bytes(raw))
    with pytest.raises(KnowledgePersistenceError):
        load_project_knowledge(path)


@pytest.mark.parametrize("failure", ["gap", "duplicate", "rollback"])
def test_manifest_sequence_attacks_fail_closed(tmp_path: pathlib.Path, failure: str) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    manifest = manifest_payload(path)
    if failure == "gap":
        manifest["authoritative_segments"][-1]["sequence_start"] += 1
    elif failure == "duplicate":
        manifest["authoritative_segments"][-1]["sequence_start"] = 1
    else:
        manifest["latest_sequence"] = 1
    write_manifest(path, manifest)
    with pytest.raises(KnowledgePersistenceError):
        load_project_knowledge(path)


def test_orphan_complete_and_partial_segments_are_never_truth(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    original = project_knowledge_semantic_hash(pack)
    segment_dir = path / "segments"
    (segment_dir / "seg-00000000000000000002-00000000000000000002-aaaaaaaaaaaaaaaa.json").write_bytes(b"{}")
    (segment_dir / ".partial.tmp").write_bytes(b"partial")
    verify = SegmentedKnowledgeStore(path).verify()
    assert verify["orphan_segments"]
    assert verify["partial_temporaries"]
    assert project_knowledge_semantic_hash(load_project_knowledge(path)) == original


@pytest.mark.parametrize(
    ("point", "new_visible"),
    [
        ("C1_BEFORE_SEGMENT_WRITE", False),
        ("C2_DURING_SEGMENT_WRITE", False),
        ("C3_SEGMENT_COMPLETE_BEFORE_MANIFEST", False),
        ("C4_DURING_MANIFEST_WRITE", False),
        ("C5_BEFORE_MANIFEST_REPLACE", False),
        ("C6_AFTER_MANIFEST_REPLACE", True),
    ],
)
def test_crash_points_expose_only_old_or_new_state(tmp_path: pathlib.Path, point: str, new_visible: bool) -> None:
    path, pack = create_store(tmp_path)
    result = internalize_evidence(pack, evidence("Port is 8000."))
    with pytest.raises(RuntimeError, match=point):
        SegmentedKnowledgeStore(path).commit_mutations(
            [result["persistence_mutation"]], expected_sequence=1,
            expected_authority_root=pack._persistence_authority_root, injector=fail_at(point),
        )
    loaded = load_project_knowledge(path)
    assert bool(loaded["all_items"]) is new_visible


def test_checkpoint_interruption_never_changes_authority(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    before = project_knowledge_semantic_hash(pack)
    with pytest.raises(RuntimeError, match="C7_DURING_CHECKPOINT_WRITE"):
        SegmentedKnowledgeStore(path).create_checkpoint(injector=fail_at("C7_DURING_CHECKPOINT_WRITE"))
    assert project_knowledge_semantic_hash(load_project_knowledge(path)) == before
    assert manifest_payload(path)["current_checkpoint"] is None


def test_compaction_preserves_records_semantics_and_as_of_history(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    hashes = {1: project_knowledge_semantic_hash(pack)}
    for index in range(5):
        pack, _ = append(pack, path, evidence(f"Fact {index}", subject_ref=f"s{index}", branch_ref=f"b{index}"))
        hashes[index + 2] = project_knowledge_semantic_hash(pack)
    store = SegmentedKnowledgeStore(path)
    before = manifest_payload(path)
    receipt = store.compact(max_segments=4, validate_full_replay=True)
    after = manifest_payload(path)
    assert receipt["status"] == "PASS"
    assert receipt["records_preserved"] == 4
    assert len(after["authoritative_segments"]) < len(before["authoritative_segments"])
    assert before["authority_root_hash"] == after["authority_root_hash"]
    assert receipt["semantic_hash_before"] == receipt["semantic_hash_after"]
    for sequence, expected in hashes.items():
        assert project_knowledge_semantic_hash(store.load(use_checkpoint=False, as_of_sequence=sequence)) == expected


def test_interrupted_compaction_keeps_old_layout(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    for index in range(3):
        pack, _ = append(pack, path, evidence(f"Fact {index}", subject_ref=f"s{index}", branch_ref=f"b{index}"))
    before = manifest_payload(path)
    expected = project_knowledge_semantic_hash(pack)
    with pytest.raises(RuntimeError, match="C8_DURING_COMPACTION"):
        SegmentedKnowledgeStore(path).compact(max_segments=3, injector=fail_at("C8_DURING_COMPACTION"))
    assert manifest_payload(path)["authoritative_segments"] == before["authoritative_segments"]
    assert project_knowledge_semantic_hash(load_project_knowledge(path)) == expected


def test_legacy_load_migration_and_explicit_rollback(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "legacy.json"
    target = tmp_path / "segmented"
    pack = internalize_evidence(new_project_knowledge_pack("legacy", "pkp_legacy"), evidence("Legacy fact."))["pack"]
    save_legacy_project_knowledge(source, pack)
    assert project_knowledge_semantic_hash(load_project_knowledge(source)) == project_knowledge_semantic_hash(pack)
    receipt = migrate_legacy_pack(source, target)
    assert receipt["legacy_retained"] is True and source.is_file()
    assert project_knowledge_semantic_hash(load_project_knowledge(target)) == project_knowledge_semantic_hash(pack)
    rollback = rollback_legacy_migration(source, target)
    assert rollback["status"] == "PASS" and source.is_file() and not target.exists()


def test_migration_failure_rolls_back_without_touching_legacy(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "legacy.json"
    target = tmp_path / "segmented"
    pack = new_project_knowledge_pack("legacy", "pkp_legacy")
    save_legacy_project_knowledge(source, pack)
    before = source.read_bytes()

    def fail_checkpoint(self, **kwargs):
        raise RuntimeError("checkpoint failed")

    monkeypatch.setattr(SegmentedKnowledgeStore, "create_checkpoint", fail_checkpoint)
    with pytest.raises(RuntimeError, match="checkpoint failed"):
        migrate_legacy_pack(source, target)
    assert source.read_bytes() == before
    assert not target.exists()


def test_retrieval_and_conversation_are_equal_between_v1_and_v2(tmp_path: pathlib.Path) -> None:
    legacy_path, v2_path = tmp_path / "legacy.json", tmp_path / "v2"
    pack = internalize_evidence(new_project_knowledge_pack("fixture", "pkp_fixture"), evidence("Payments retry twice.", subject_ref="payments.retry", branch_ref="payments"))["pack"]
    save_legacy_project_knowledge(legacy_path, pack)
    migrate_legacy_pack(legacy_path, v2_path)
    v1, v2 = load_project_knowledge(legacy_path), load_project_knowledge(v2_path)
    query = {"goal": "payments retry", "require_relevance": True, "max_items": 10}
    assert retrieve_relevant_knowledge(v1, query) == retrieve_relevant_knowledge(v2, query)
    request = ConversationRequest("What is the payments retry policy?", retrieval_constraints={"max_nodes": 10})
    assert ConversationService(None).answer(request, v1, provider_enabled=False) == ConversationService(None).answer(request, v2, provider_enabled=False)


def test_raw_evidence_byte_fidelity(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    raw = "line one\r\nline two\n雪\x00end"
    pack, _ = append(pack, path, evidence(raw, subject_ref="raw", branch_ref="raw"))
    assert load_project_knowledge(path)["all_items"][0]["content"].encode("utf-8") == raw.encode("utf-8")


def test_path_traversal_and_cross_pack_injection_fail_closed(tmp_path: pathlib.Path) -> None:
    path, _ = create_store(tmp_path)
    manifest = manifest_payload(path)
    manifest["authoritative_segments"][0]["path"] = "../escape.json"
    write_manifest(path, manifest)
    with pytest.raises(KnowledgePersistenceError, match="UNSAFE_SEGMENT_PATH"):
        load_project_knowledge(path)


def test_pack_write_lock_is_enforced(tmp_path: pathlib.Path) -> None:
    path, _ = create_store(tmp_path)
    with _WriteLock(path):
        with pytest.raises(KnowledgePersistenceError, match="PACK_WRITE_LOCKED"):
            with _WriteLock(path):
                pass


def test_oversized_record_is_rejected_without_commit(tmp_path: pathlib.Path) -> None:
    policy = PersistencePolicy(max_record_bytes=512)
    path, pack = create_store(tmp_path, policy=policy)
    result = internalize_evidence(pack, evidence("x" * 1024))
    with pytest.raises(KnowledgePersistenceError, match="PERSISTENCE_RECORD_TOO_LARGE"):
        SegmentedKnowledgeStore(path, policy=policy).commit_mutations([result["persistence_mutation"]])
    assert load_project_knowledge(path)["all_items"] == []


def test_unknown_format_fails_closed(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "unknown"
    path.mkdir()
    (path / "other").write_text("x", encoding="utf-8")
    with pytest.raises(KnowledgePersistenceError, match="UNKNOWN_PERSISTENCE_LAYOUT"):
        load_project_knowledge(path)


def test_schema_documents_accept_written_v2_artifacts(tmp_path: pathlib.Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    SegmentedKnowledgeStore(path).create_checkpoint()
    manifest = manifest_payload(path)
    segment = json.loads((path / manifest["authoritative_segments"][0]["path"]).read_text(encoding="utf-8"))
    checkpoint = _read_document(path / manifest["current_checkpoint"]["path"], 1024 * 1024 * 1024)[0]
    for value, schema_name in (
        (manifest, "project_knowledge_manifest_v2.schema.json"),
        (segment, "project_knowledge_segment_v2.schema.json"),
        (checkpoint, "project_knowledge_checkpoint_v2.schema.json"),
    ):
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(value)


def test_policy_reports_checkpoint_and_compaction_due_without_hiding_maintenance(tmp_path: pathlib.Path) -> None:
    policy = PersistencePolicy(checkpoint_mutation_interval=2, checkpoint_tail_bytes=1024 * 1024,
                               compaction_segment_threshold=3, compaction_batch_size=2,
                               compaction_tail_bytes=1024 * 1024)
    path, pack = create_store(tmp_path, policy=policy)
    result = internalize_evidence(pack, evidence("First fact."))
    first = SegmentedKnowledgeStore(path, policy=policy).commit_mutations([result["persistence_mutation"]])
    assert first["checkpoint_due"] is True
    pack = load_project_knowledge(path)
    result = internalize_evidence(pack, evidence("Second fact.", subject_ref="second", branch_ref="second"))
    second = SegmentedKnowledgeStore(path, policy=policy).commit_mutations([result["persistence_mutation"]])
    assert second["compaction_due"] is True
    assert second["checkpoint_bytes_written"] == second["compaction_bytes_written"] == 0


def test_manifest_tampering_and_unknown_future_version_fail_closed(tmp_path: pathlib.Path) -> None:
    path, _ = create_store(tmp_path)
    document = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    document["payload"]["latest_sequence"] = 99
    (path / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(KnowledgePersistenceError, match="PERSISTENCE_CHECKSUM_MISMATCH"):
        load_project_knowledge(path)

    # A self-consistent document with an unknown version still fails closed.
    manifest = document["payload"]
    manifest["format_version"] = "99.0"
    write_manifest(path, manifest)
    with pytest.raises(KnowledgePersistenceError, match="UNSUPPORTED_PERSISTENCE_FORMAT"):
        load_project_knowledge(path)


def test_cross_pack_segment_and_record_checksum_spoof_fail_closed(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("Port is 8000."))
    manifest = manifest_payload(path)
    descriptor = manifest["authoritative_segments"][-1]
    segment_path = path / descriptor["path"]
    segment = json.loads(segment_path.read_text(encoding="utf-8"))
    segment["pack_id"] = "pkp_other"
    core = {key: value for key, value in segment.items() if key != "content_checksum"}
    from cgnk_knowledge.persistence import _value_hash

    segment["content_checksum"] = _value_hash(core)
    raw = _json_bytes(segment)
    segment_path.write_bytes(raw)
    descriptor["content_checksum"] = segment["content_checksum"]
    descriptor["file_hash"] = _sha256(raw)
    descriptor["file_bytes"] = len(raw)
    write_manifest(path, manifest)
    with pytest.raises(KnowledgePersistenceError, match="CROSS_PACK_SEGMENT"):
        load_project_knowledge(path)

    # Restore, then alter a canonical record while recomputing only outer hashes.
    path2, pack2 = create_store(tmp_path / "second")
    pack2, _ = append(pack2, path2, evidence("Port is 8000."))
    manifest2 = manifest_payload(path2)
    descriptor2 = manifest2["authoritative_segments"][-1]
    segment_path2 = path2 / descriptor2["path"]
    segment2 = json.loads(segment_path2.read_text(encoding="utf-8"))
    segment2["records"][0]["payload"]["items"][0]["content"] = "spoofed"
    core2 = {key: value for key, value in segment2.items() if key != "content_checksum"}
    segment2["content_checksum"] = _value_hash(core2)
    raw2 = _json_bytes(segment2)
    segment_path2.write_bytes(raw2)
    descriptor2["content_checksum"] = segment2["content_checksum"]
    descriptor2["file_hash"] = _sha256(raw2)
    descriptor2["file_bytes"] = len(raw2)
    write_manifest(path2, manifest2)
    with pytest.raises(KnowledgePersistenceError, match="MUTATION_CHECKSUM_MISMATCH"):
        load_project_knowledge(path2)


def test_old_checkpoint_replay_is_rejected_then_segments_replay(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    pack, _ = append(pack, path, evidence("First."))
    store = SegmentedKnowledgeStore(path)
    store.create_checkpoint()
    first_manifest = manifest_payload(path)
    old_checkpoint = (path / first_manifest["current_checkpoint"]["path"]).read_bytes()
    pack = load_project_knowledge(path)
    pack, _ = append(pack, path, evidence("Second.", subject_ref="second", branch_ref="second"))
    store.create_checkpoint()
    current = manifest_payload(path)
    current_path = path / current["current_checkpoint"]["path"]
    current_path.write_bytes(old_checkpoint)
    current["current_checkpoint"]["file_hash"] = _sha256(old_checkpoint)
    current["current_checkpoint"]["file_bytes"] = len(old_checkpoint)
    write_manifest(path, current)
    loaded = store.load()
    assert loaded._load_receipt["checkpoint_status"].startswith("REJECTED_REPLAYED")
    assert {row["content"] for row in loaded["all_items"]} == {"First.", "Second."}


def test_untrusted_evidence_cannot_choose_physical_metadata(tmp_path: pathlib.Path) -> None:
    path, pack = create_store(tmp_path)
    hostile = evidence("Safe fact.", segment_id="../../escape", sequence=999,
                       checkpoint_path="C:/outside", manifest={"format_version": "99"})
    pack, _ = append(pack, path, hostile)
    manifest = manifest_payload(path)
    assert manifest["latest_sequence"] == 2
    assert all(row["path"].startswith("segments/") for row in manifest["authoritative_segments"])
    assert not (tmp_path / "escape").exists()


def _migration_shape(name: str) -> dict:
    pack = new_project_knowledge_pack(f"migration-{name}", f"pkp_migration_{name}")
    if name == "empty":
        return pack
    first = internalize_evidence(pack, evidence(f"{name} base fact.", subject_ref=f"{name}.subject", branch_ref=name))["pack"]
    first_id = first["all_items"][0]["id"]
    if name == "duplicate":
        return internalize_evidence(first, evidence(f"{name} base fact.", source_ref="source:second", subject_ref=f"{name}.subject", branch_ref=name))["pack"]
    if name == "supersession":
        return internalize_evidence(first, evidence("new version", source_ref="source:new", source_version="2", subject_ref=f"{name}.subject", branch_ref=name))["pack"]
    if name in {"contradiction", "correction", "retraction"}:
        relation = {"contradiction": "CONTRADICTING", "correction": "CORRECTION", "retraction": "RETRACTION"}[name]
        return internalize_evidence(first, evidence(name, source_ref="source:new", relation=relation, target_id=first_id,
                                                    subject_ref=f"{name}.subject", branch_ref=name))["pack"]
    if name == "derived":
        return upsert_knowledge_items(first, [make_derived_abstraction("derived.node", "derived value", [first_id], branch_ref=name)])
    if name == "raw_bytes":
        return internalize_evidence(first, evidence("raw\r\nbytes\n雪", source_ref="source:raw", subject_ref="raw", branch_ref="raw"))["pack"]
    if name == "cross_domain":
        return internalize_evidence(first, evidence("module fact", scope="module", source_ref="source:module", subject_ref="module", branch_ref="module"))["pack"]
    return first


@pytest.mark.parametrize(
    "shape",
    ["empty", "novel", "duplicate", "supersession", "contradiction", "correction", "retraction", "derived", "raw_bytes", "cross_domain"],
)
def test_migration_compatibility_gate_ten_shapes(tmp_path: pathlib.Path, shape: str) -> None:
    source, target = tmp_path / f"{shape}.json", tmp_path / f"{shape}.v2"
    original = _migration_shape(shape)
    save_legacy_project_knowledge(source, original)
    migrate_legacy_pack(source, target)
    v1, v2 = load_project_knowledge(source), load_project_knowledge(target)
    assert project_knowledge_semantic_hash(v1) == project_knowledge_semantic_hash(v2)
    query = {"goal": shape, "require_relevance": False, "include_archived": True, "include_reference": True, "max_items": 50}
    assert retrieve_relevant_knowledge(v1, query) == retrieve_relevant_knowledge(v2, query)
    request = ConversationRequest(f"What evidence exists for {shape}?", retrieval_constraints={"max_nodes": 20, "include_archived": True})
    left = ConversationService(None).answer(request, v1, provider_enabled=False)
    right = ConversationService(None).answer(request, v2, provider_enabled=False)
    left.pop("elapsed_ms", None)
    right.pop("elapsed_ms", None)
    assert left == right

    update = evidence("post migration update", subject_ref="post.migration", branch_ref="post")
    left_update = internalize_evidence(v1, update)["pack"]
    right_result = internalize_evidence(v2, update)
    save_legacy_project_knowledge(source, left_update)
    save_project_knowledge(target, right_result["pack"], mutation=right_result["persistence_mutation"])
    assert project_knowledge_semantic_hash(load_project_knowledge(source)) == project_knowledge_semantic_hash(load_project_knowledge(target))


def test_application_service_commits_delta_and_detects_stale_writer(tmp_path: pathlib.Path) -> None:
    from cgkn.application.knowledge_growth import KnowledgeInternalizationService

    path, stale = create_store(tmp_path)
    service = KnowledgeInternalizationService()
    first = service.internalize_persisted(str(path), evidence("First."))
    assert first["receipt"]["persistence"]["sequence_end"] == 2
    stale_result = internalize_evidence(stale, evidence("Stale.", subject_ref="stale", branch_ref="stale"))
    with pytest.raises(KnowledgePersistenceError, match="PACK_SEQUENCE_CONFLICT"):
        save_project_knowledge(path, stale_result["pack"], mutation=stale_result["persistence_mutation"])
