from __future__ import annotations

import pytest

from cgkn.artifacts import ArtifactInstance, ArtifactStore, ArtifactTypeRegistry, Producer, Provenance
from cgkn.artifacts.lineage import build_lineage, render_lineage
from cgkn.artifacts.types import ArtifactValidationError


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.happy_path, pytest.mark.roundtrip, pytest.mark.determinism]


def _write(store: ArtifactStore, artifact_id: str, text: str, parents=()):
    artifact = ArtifactInstance(artifact_id, "artifact.raw_requirement@1", "r", Producer("n", "module.test@1"), {"text": text}, Provenance(input_artifact_refs=tuple(parents)))
    return store.write_artifact(artifact)


def test_multiple_parent_lineage_and_render_order(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    second = _write(store, "ai.parent.002", "second")
    first = _write(store, "ai.parent.001", "first")
    child = _write(store, "ai.child.001", "child", (second, first))
    tree = build_lineage(store, child)
    assert [item["artifactRef"]["artifactInstanceId"] for item in tree["inputs"]] == ["ai.parent.001", "ai.parent.002"]
    rendered = render_lineage(tree)
    assert rendered.splitlines()[0].startswith("ai.child.001")
    assert rendered == render_lineage(tree)


@pytest.mark.negative
def test_unknown_parent_missing_artifact_and_tamper_fail_closed(tmp_path) -> None:
    store = ArtifactStore(tmp_path, ArtifactTypeRegistry(ROOT))
    missing = __import__("cgkn.artifacts", fromlist=["ArtifactRef"]).ArtifactRef("ai.missing.001", "artifact.raw_requirement@1", "sha256:" + "0" * 64)
    with pytest.raises(ArtifactValidationError):
        _write(store, "ai.child.001", "child", (missing,))
    with pytest.raises(ArtifactValidationError):
        build_lineage(store, "ai.missing.001")


@pytest.mark.negative
def test_cycle_is_rejected_even_for_corrupt_store_projection() -> None:
    class Item:
        def __init__(self, name):
            self.id = name; self.status = "fresh"; self.producer = Producer("n", "m@1"); self.provenance = Provenance(); self.ref = type("R", (), {"as_dict": lambda _self: {"artifactInstanceId": name, "artifactType": "artifact.x@1", "contentHash": "sha256:" + "0" * 64}})()
    item = Item("a")
    item.provenance = Provenance(input_artifact_refs=(type("Ref", (), {"artifact_instance_id": "a"})(),))
    class Store:
        def resolve_artifact_ref(self, _value): return item
    with pytest.raises(ArtifactValidationError, match="cycle"):
        build_lineage(Store(), "a")
