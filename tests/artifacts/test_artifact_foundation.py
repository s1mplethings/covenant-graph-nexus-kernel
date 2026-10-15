from __future__ import annotations

import json
import os
import pathlib

import pytest

from cgkn.artifacts import ArtifactInstance, ArtifactRef, ArtifactStore, ArtifactTypeRegistry, Producer, Provenance
from cgkn.artifacts.types import ArtifactValidationError


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def _artifact(store: ArtifactStore, artifact_id: str = "ai.goal.001") -> ArtifactInstance:
    return ArtifactInstance(
        artifact_id,
        "artifact.raw_requirement@1",
        "run-1",
        Producer("node-1", "module.test@1", "goal"),
        {"text": "ship"},
        Provenance(),
    )


@pytest.mark.parametrize(
    "artifact_id, artifact_type, digest",
    [("../escape", "artifact.goal@1", "sha256:" + "0" * 64), ("a", "goal", "sha256:" + "0" * 64), ("a", "artifact.goal@1", "bad")],
)
@pytest.mark.negative
@pytest.mark.security
def test_artifact_ref_rejects_invalid_identity(artifact_id: str, artifact_type: str, digest: str) -> None:
    with pytest.raises(ValueError):
        ArtifactRef(artifact_id, artifact_type, digest)


@pytest.mark.negative
@pytest.mark.security
def test_store_rejects_overwrite_and_detects_tampering(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    artifact = _artifact(store)
    store.write_artifact(artifact)
    with pytest.raises(ArtifactValidationError, match="already exists"):
        store.write_artifact(artifact)
    path = tmp_path / "artifacts" / "ai.goal.001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"]["text"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.verify_artifact_hash(artifact.ref) is False


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks is not reliably permitted on Windows")
@pytest.mark.security
def test_store_rejects_artifact_directory_symlink_escape(tmp_path) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    run_dir.mkdir()
    outside.mkdir()
    (run_dir / "artifacts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactValidationError, match="escapes"):
        ArtifactStore(run_dir, ArtifactTypeRegistry(ROOT))


@pytest.mark.roundtrip
def test_artifact_round_trip_and_deterministic_identity(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    artifact = _artifact(store)
    ref = store.write_artifact(artifact)
    assert ArtifactRef.from_dict(ref.as_dict()) == ref
    assert store.read_artifact(ref.artifact_instance_id).as_dict() == artifact.as_dict()


@pytest.mark.negative
def test_duplicate_lineage_self_lineage_and_self_supersedes_are_rejected(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    parent = _artifact(store, "ai.parent.001")
    parent_ref = store.write_artifact(parent)
    common = dict(artifact_type="artifact.raw_requirement@1", run_id="run-1", producer=Producer("node", "module.test@1"), content={"text": "x"})
    with pytest.raises(ValueError, match="duplicate edge"):
        ArtifactInstance("ai.child.001", provenance=Provenance(input_artifact_refs=(parent_ref, parent_ref)), **common)
    own_ref = ArtifactRef("ai.self.001", "artifact.raw_requirement@1", "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="reference itself"):
        ArtifactInstance("ai.self.001", provenance=Provenance(input_artifact_refs=(own_ref,)), **common)
    with pytest.raises(ValueError, match="supersede itself"):
        ArtifactInstance("ai.super.001", provenance=Provenance(), supersedes="ai.super.001", **common)


@pytest.mark.negative
@pytest.mark.security
def test_corrupt_index_artifact_missing_blob_and_path_escape_fail_closed(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    store.index_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="index is unreadable"):
        store.list_artifacts()
    store.index_path.write_text(json.dumps({"kind": "ArtifactIndex", "schemaVersion": "1", "artifacts": [{"artifactInstanceId": "ai.missing.001", "artifactType": "artifact.raw_requirement@1", "contentHash": "sha256:" + "0" * 64, "status": "fresh", "path": "artifacts/ai.missing.001.json"}]}), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="not found"):
        store.read_artifact("ai.missing.001")
    with pytest.raises(ArtifactValidationError, match="escapes"):
        store._assert_local_path(tmp_path.parent / "escape.json")


@pytest.mark.negative
def test_status_transition_and_supersedes_validation(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    artifact = _artifact(store)
    store.write_artifact(artifact)
    store.set_status(artifact.id, "invalid")
    with pytest.raises(ArtifactValidationError, match="transition"):
        store.set_status(artifact.id, "fresh")
    missing = _artifact(store, "ai.next.001")
    missing.supersedes = "ai.unknown.001"
    with pytest.raises(ArtifactValidationError, match="does not exist"):
        store.write_artifact(missing)


@pytest.mark.fault_injection
def test_fsync_failure_cleans_temp_and_reports_no_success(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    monkeypatch.setattr("cgkn.artifacts.store.os.fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync failed")))
    with pytest.raises(OSError, match="fsync failed"):
        store.write_artifact(_artifact(store))
    assert not (tmp_path / "artifacts" / "ai.goal.001.json").exists()
    assert not list((tmp_path / "artifacts").glob("*.tmp"))


@pytest.mark.fault_injection
@pytest.mark.recovery
def test_index_replace_failure_rolls_back_blob_and_preserves_index(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    before = store.index_path.read_bytes()
    real_replace = os.replace
    def fail_index(source, target):
        if __import__("pathlib").Path(target) == store.index_path:
            raise OSError("replace failed")
        return real_replace(source, target)
    monkeypatch.setattr("cgkn.artifacts.store.os.replace", fail_index)
    with pytest.raises(OSError, match="replace failed"):
        store.write_artifact(_artifact(store))
    assert store.index_path.read_bytes() == before
    assert not (tmp_path / "artifacts" / "ai.goal.001.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.negative
def test_corrupt_blob_and_index_identity_mismatch_fail_closed(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    artifact = _artifact(store)
    store.write_artifact(artifact)
    path = tmp_path / "artifacts" / f"{artifact.id}.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="corrupt"):
        store.read_artifact(artifact.id)


@pytest.mark.negative
@pytest.mark.parametrize("payload, message", [
    ({}, "schema"),
    ({"kind": "ArtifactIndex", "schemaVersion": "1", "artifacts": [1]}, "row"),
    ({"kind": "ArtifactIndex", "schemaVersion": "1", "artifacts": [{"artifactInstanceId": "../bad", "status": "fresh", "path": "artifacts/../bad.json"}]}, "unsafe"),
    ({"kind": "ArtifactIndex", "schemaVersion": "1", "artifacts": [{"artifactInstanceId": "a", "status": "bad", "path": "artifacts/a.json"}]}, "status"),
    ({"kind": "ArtifactIndex", "schemaVersion": "1", "artifacts": [{"artifactInstanceId": "a", "status": "fresh", "path": "wrong"}]}, "path mismatch"),
    ({"kind": "ArtifactIndex", "schemaVersion": "1", "artifacts": [{"artifactInstanceId": "a", "status": "fresh", "path": "artifacts/a.json"}, {"artifactInstanceId": "a", "status": "fresh", "path": "artifacts/a.json"}]}, "duplicate"),
])
def test_index_integrity_variants_fail_closed(tmp_path, payload, message) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    store.index_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match=message):
        store.list_artifacts()


@pytest.mark.security
def test_index_and_artifact_symlink_flags_fail_closed_without_os_privilege(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    real = pathlib.Path.is_symlink
    monkeypatch.setattr(pathlib.Path, "is_symlink", lambda path: True if path in {store.index_path, store.artifacts_dir / "a.json"} else real(path))
    with pytest.raises(ArtifactValidationError, match="index must not"):
        store._load_index()
    with pytest.raises(ArtifactValidationError, match="artifact path"):
        store._path("a")


@pytest.mark.negative
def test_store_query_filters_identity_mismatch_consumers_and_missing_rows(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    first = _artifact(store, "ai.goal.001"); store.write_artifact(first)
    second = _artifact(store, "ai.goal.002"); store.write_artifact(second); store.set_status(second.id, "stale")
    assert store.allocate_id("artifact.raw_requirement@1") == "ai.raw-requirement.001"
    assert [item.id for item in store.list_artifacts(status="fresh")] == [first.id]
    assert store.list_artifacts(artifact_type="artifact.missing@1") == []
    mismatched = {**first.ref.as_dict(), "contentHash": "sha256:" + "0" * 64}
    with pytest.raises(ArtifactValidationError, match="identity mismatch"):
        store.resolve_artifact_ref(mismatched)
    assert store.latest_produced_by_node("node-1", "goal").id == first.id
    assert store.latest_produced_by_node("missing", "goal") is None
    store.register_consumer(first.id, "b"); store.register_consumer(first.id, "a"); store.register_consumer(first.id, "a")
    assert store.find_consumers(first.ref) == ["a", "b"]
    with pytest.raises(ArtifactValidationError, match="not indexed"):
        store.find_consumers("missing")
    with pytest.raises(ArtifactValidationError, match="invalid artifact status"):
        store.set_status(first.id, "unknown")


@pytest.mark.negative
@pytest.mark.fault_injection
def test_validation_dependency_hash_and_internal_hash_mismatch_fail_closed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    parent = _artifact(store, "ai.parent.001"); parent_ref = store.write_artifact(parent)
    child = ArtifactInstance("ai.child.001", "artifact.raw_requirement@1", "run-1", Producer("node", "module.test@1"), {"text": "child"}, Provenance(input_artifact_refs=(parent_ref,)))
    monkeypatch.setattr(store, "verify_artifact_hash", lambda _value: False)
    with pytest.raises(ArtifactValidationError, match="input artifact hash"):
        store.write_artifact(child)
    class Broken:
        artifact_type = "artifact.raw_requirement@1"; content = {"text": "x"}; content_hash = "bad"
        ref = type("Ref", (), {"content_hash": "other"})()
        provenance = Provenance()
    with pytest.raises(ArtifactValidationError, match="inconsistent"):
        store.validate_artifact(Broken())


@pytest.mark.negative
@pytest.mark.parametrize("changes,match", [
    ({"run_id": ""}, "run_id"),
    ({"producer": Producer("", "module@1")}, "producer"),
    ({"producer": Producer("node", "")}, "producer"),
    ({"status": "unknown"}, "status"),
])
def test_artifact_instance_rejects_missing_identity_and_invalid_status(changes, match) -> None:
    values = {"id": "ai.valid.001", "artifact_type": "artifact.raw_requirement@1", "run_id": "r", "producer": Producer("node", "module@1"), "content": {"text": "x"}, "provenance": Provenance()}
    values.update(changes)
    with pytest.raises(ValueError, match=match):
        ArtifactInstance(**values)
