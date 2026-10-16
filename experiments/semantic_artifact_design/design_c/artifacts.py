from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from ..common.canonical import canonical_hash, freeze, thaw, verify_content_hash
from ..common.schemas import validate_payload


FAMILY_BY_KIND = {
    "project.contract@1": "CONTRACT", "work_unit.contract@1": "CONTRACT", "test.contract@1": "CONTRACT", "repair.directive@1": "CONTRACT",
    "project.structure@1": "STATE", "interface.manifest@1": "STATE", "project.snapshot@1": "STATE",
    "test.result@1": "EVIDENCE", "failure.evidence@1": "EVIDENCE", "acceptance.receipt@1": "EVIDENCE",
}


@dataclass(frozen=True)
class FamilyArtifact:
    artifact_id: str
    kind: str
    schema_version: str
    subject_ref: str
    payload: Mapping[str, Any]
    inputs: tuple[str, ...]
    revision: int
    producer_ref: str
    content_hash: str
    FAMILY: ClassVar[str] = ""

    def __post_init__(self) -> None:
        if FAMILY_BY_KIND.get(self.kind) != self.FAMILY or self.schema_version != "1.0" or self.revision < 1:
            raise ValueError("artifact kind does not belong to semantic family")
        validate_payload(self.kind, self.payload)
        object.__setattr__(self, "payload", freeze(self.payload))

    def as_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "family": self.FAMILY, "kind": self.kind, "schema_version": self.schema_version,
                "subject_ref": self.subject_ref, "scope": self.subject_ref, "revision": self.revision, "derived_from": list(self.inputs),
                "producer_ref": self.producer_ref, "payload": thaw(self.payload), "content_hash": self.content_hash}


class ContractArtifact(FamilyArtifact): FAMILY = "CONTRACT"
class StateArtifact(FamilyArtifact): FAMILY = "STATE"
class EvidenceArtifact(FamilyArtifact): FAMILY = "EVIDENCE"
FAMILIES = {"CONTRACT": ContractArtifact, "STATE": StateArtifact, "EVIDENCE": EvidenceArtifact}


class DesignCAdapter:
    design_id = "C"

    def create(self, kind: str, subject_ref: str, payload: Mapping[str, Any], *, producer_ref: str = "experiment", inputs: tuple[str, ...] = (), revision: int = 1) -> FamilyArtifact:
        family = FAMILY_BY_KIND.get(kind)
        if family is None:
            raise ValueError(f"unknown semantic artifact kind: {kind}")
        validate_payload(kind, payload)
        seed = {"family": family, "kind": kind, "schema_version": "1.0", "subject_ref": subject_ref, "scope": subject_ref,
                "revision": revision, "derived_from": list(inputs), "producer_ref": producer_ref, "payload": dict(payload)}
        identity = f"{kind}:{canonical_hash(seed)[7:23]}"
        body = {"artifact_id": identity} | seed
        return FAMILIES[family](identity, kind, "1.0", subject_ref, payload, tuple(inputs), revision, producer_ref, canonical_hash(body))

    def load(self, value: Mapping[str, Any]) -> FamilyArtifact:
        expected = {"artifact_id", "family", "kind", "schema_version", "subject_ref", "scope", "revision", "derived_from", "producer_ref", "payload", "content_hash"}
        if set(value) != expected or value.get("scope") != value.get("subject_ref"):
            raise ValueError("malformed semantic family envelope")
        verify_content_hash(value)
        family = str(value["family"])
        try:
            cls = FAMILIES[family]
        except KeyError as exc:
            raise ValueError("unknown semantic artifact family") from exc
        return cls(str(value["artifact_id"]), str(value["kind"]), str(value["schema_version"]), str(value["subject_ref"]), dict(value["payload"]), tuple(str(item) for item in value["derived_from"]), int(value["revision"]), str(value["producer_ref"]), str(value["content_hash"]))

    @staticmethod
    def as_dict(artifact: FamilyArtifact) -> dict[str, Any]:
        return artifact.as_dict()

    def validate_graph(self, artifacts: tuple[FamilyArtifact, ...], *, current_revisions: Mapping[str, int] | None = None) -> None:
        from ..design_a.artifacts import _validate_graph
        _validate_graph(artifacts, current_revisions)

    @staticmethod
    def complexity() -> Mapping[str, int]:
        return {"core_types": 4, "schema_count": 10}


ADAPTER = DesignCAdapter()
