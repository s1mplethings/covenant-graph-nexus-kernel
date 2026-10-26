from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import re

from .hash import content_hash


ARTIFACT_STATUSES = {"fresh", "stale", "invalid", "superseded"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_ARTIFACT_TYPE = re.compile(r"^artifact\.[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$")
_CONTENT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_artifact_id(value: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("artifact instance id is unsafe")


def validate_artifact_type(value: str) -> None:
    if not _ARTIFACT_TYPE.fullmatch(value):
        raise ValueError("artifact_type must be a versioned artifact ref")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ArtifactRef:
    artifact_instance_id: str
    artifact_type: str
    content_hash: str

    def __post_init__(self) -> None:
        validate_artifact_id(self.artifact_instance_id)
        validate_artifact_type(self.artifact_type)
        if not _CONTENT_HASH.fullmatch(self.content_hash):
            raise ValueError("content_hash must be a canonical sha256 value")

    def as_dict(self) -> dict[str, str]:
        return {
            "artifactInstanceId": self.artifact_instance_id,
            "artifactType": self.artifact_type,
            "contentHash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArtifactRef":
        return cls(
            artifact_instance_id=str(value["artifactInstanceId"]),
            artifact_type=str(value["artifactType"]),
            content_hash=str(value["contentHash"]),
        )


@dataclass(frozen=True)
class Producer:
    node_id: str
    module_ref: str
    output_port: str = ""

    def as_dict(self) -> dict[str, str]:
        result = {"nodeId": self.node_id, "moduleRef": self.module_ref}
        if self.output_port:
            result["outputPort"] = self.output_port
        return result


@dataclass(frozen=True)
class Provenance:
    input_artifact_refs: tuple[ArtifactRef, ...] = ()
    source_refs: tuple[str, ...] = ()
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "inputArtifactRefs": [item.as_dict() for item in self.input_artifact_refs],
            "sourceRefs": list(self.source_refs),
            "provider": self.provider,
            "model": self.model,
            "promptVersion": self.prompt_version,
        }


@dataclass
class ArtifactInstance:
    id: str
    artifact_type: str
    run_id: str
    producer: Producer
    content: dict[str, Any]
    provenance: Provenance
    content_hash: str = ""
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "1"
    status: str = "fresh"
    supersedes: str | None = None

    def __post_init__(self) -> None:
        validate_artifact_id(self.id)
        validate_artifact_type(self.artifact_type)
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.producer.node_id or not self.producer.module_ref:
            raise ValueError("producer nodeId and moduleRef are required")
        if self.status not in ARTIFACT_STATUSES:
            raise ValueError(f"invalid artifact status: {self.status}")
        if self.supersedes == self.id:
            raise ValueError("artifact cannot supersede itself")
        refs = [item.artifact_instance_id for item in self.provenance.input_artifact_refs]
        if self.id in refs:
            raise ValueError("artifact cannot reference itself as input")
        if len(refs) != len(set(refs)):
            raise ValueError("artifact input lineage contains a duplicate edge")
        calculated = content_hash(self.content)
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("contentHash does not match canonicalized content")
        self.content_hash = calculated

    @property
    def ref(self) -> ArtifactRef:
        return ArtifactRef(self.id, self.artifact_type, self.content_hash)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ArtifactInstance",
            "id": self.id,
            "artifactType": self.artifact_type,
            "runId": self.run_id,
            "producer": self.producer.as_dict(),
            "createdAt": self.created_at,
            "content": self.content,
            "provenance": self.provenance.as_dict(),
            "contentHash": self.content_hash,
            "schemaVersion": self.schema_version,
            "status": self.status,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArtifactInstance":
        producer = value["producer"]
        provenance = value["provenance"]
        return cls(
            id=str(value["id"]),
            artifact_type=str(value["artifactType"]),
            run_id=str(value["runId"]),
            producer=Producer(
                node_id=str(producer["nodeId"]),
                module_ref=str(producer["moduleRef"]),
                output_port=str(producer.get("outputPort", "")),
            ),
            content=dict(value["content"]),
            provenance=Provenance(
                input_artifact_refs=tuple(
                    ArtifactRef.from_dict(item) for item in provenance.get("inputArtifactRefs", [])
                ),
                source_refs=tuple(str(item) for item in provenance.get("sourceRefs", [])),
                provider=provenance.get("provider"),
                model=provenance.get("model"),
                prompt_version=provenance.get("promptVersion"),
            ),
            content_hash=str(value.get("contentHash", "")),
            created_at=str(value.get("createdAt", utc_now())),
            schema_version=str(value.get("schemaVersion", "1")),
            status=str(value.get("status", "fresh")),
            supersedes=value.get("supersedes"),
        )
