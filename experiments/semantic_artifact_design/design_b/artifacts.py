from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from ..common.canonical import canonical_hash, freeze, thaw, verify_content_hash
from ..common.schemas import KINDS, validate_payload


@dataclass(frozen=True)
class SemanticArtifact:
    artifact_id: str
    kind: str
    schema_version: str
    subject_ref: str
    producer_ref: str
    inputs: tuple[str, ...]
    revision: int
    payload: Mapping[str, Any]
    created_at: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS or self.schema_version != "1.0" or not self.subject_ref or self.revision < 1:
            raise ValueError("invalid semantic artifact identity or version")
        validate_payload(self.kind, self.payload)
        object.__setattr__(self, "payload", freeze(self.payload))

    def as_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "kind": self.kind, "schema_version": self.schema_version, "subject_ref": self.subject_ref,
                "producer_ref": self.producer_ref, "inputs": list(self.inputs), "revision": self.revision, "payload": thaw(self.payload),
                "created_at": self.created_at, "content_hash": self.content_hash}


class SemanticSchemaRegistry:
    def validate(self, kind: str, payload: Mapping[str, Any]) -> None:
        validate_payload(kind, payload)


class DesignBAdapter:
    design_id = "B"

    def __init__(self) -> None:
        self.registry = SemanticSchemaRegistry()

    def create(self, kind: str, subject_ref: str, payload: Mapping[str, Any], *, producer_ref: str = "experiment", inputs: tuple[str, ...] = (), revision: int = 1) -> SemanticArtifact:
        self.registry.validate(kind, payload)
        created = "deterministic"
        seed = {"kind": kind, "schema_version": "1.0", "subject_ref": subject_ref, "producer_ref": producer_ref, "inputs": list(inputs), "revision": revision, "payload": dict(payload), "created_at": created}
        identity = f"{kind}:{canonical_hash(seed)[7:23]}"
        body = {"artifact_id": identity} | seed
        return SemanticArtifact(identity, kind, "1.0", subject_ref, producer_ref, tuple(inputs), revision, payload, created, canonical_hash(body))

    def load(self, value: Mapping[str, Any]) -> SemanticArtifact:
        expected = {"artifact_id", "kind", "schema_version", "subject_ref", "producer_ref", "inputs", "revision", "payload", "created_at", "content_hash"}
        if set(value) != expected:
            raise ValueError("malformed semantic envelope")
        verify_content_hash(value)
        return SemanticArtifact(str(value["artifact_id"]), str(value["kind"]), str(value["schema_version"]), str(value["subject_ref"]), str(value["producer_ref"]), tuple(str(item) for item in value["inputs"]), int(value["revision"]), dict(value["payload"]), str(value["created_at"]), str(value["content_hash"]))

    @staticmethod
    def as_dict(artifact: SemanticArtifact) -> dict[str, Any]:
        return artifact.as_dict()

    def validate_graph(self, artifacts: tuple[SemanticArtifact, ...], *, current_revisions: Mapping[str, int] | None = None) -> None:
        from ..design_a.artifacts import _validate_graph
        _validate_graph(artifacts, current_revisions)

    @staticmethod
    def complexity() -> Mapping[str, int]:
        return {"core_types": 2, "schema_count": 10}


ADAPTER = DesignBAdapter()
