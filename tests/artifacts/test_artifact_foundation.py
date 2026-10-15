from __future__ import annotations

import json
import os

import pytest

from cgkn.artifacts import ArtifactInstance, ArtifactRef, ArtifactStore, ArtifactTypeRegistry, Producer, Provenance
from cgkn.artifacts.types import ArtifactValidationError


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


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
def test_artifact_ref_rejects_invalid_identity(artifact_id: str, artifact_type: str, digest: str) -> None:
    with pytest.raises(ValueError):
        ArtifactRef(artifact_id, artifact_type, digest)


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
def test_store_rejects_artifact_directory_symlink_escape(tmp_path) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    run_dir.mkdir()
    outside.mkdir()
    (run_dir / "artifacts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactValidationError, match="escapes"):
        ArtifactStore(run_dir, ArtifactTypeRegistry(ROOT))
