from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from ..common.canonical import canonical_hash, freeze, thaw, verify_content_hash
from ..common.schemas import validate_payload


@dataclass(frozen=True)
class TypedArtifact:
    subject_ref: str
    payload: Mapping[str, Any]
    producer_ref: str = "experiment"
    inputs: tuple[str, ...] = ()
    revision: int = 1
    artifact_id: str = ""
    content_hash: str = ""
    KIND: ClassVar[str] = ""

    def __post_init__(self) -> None:
        if not self.subject_ref or self.revision < 1:
            raise ValueError("artifact subject and positive revision are required")
        validate_payload(self.KIND, self.payload)
        object.__setattr__(self, "payload", freeze(self.payload))
        seed = {"kind": self.KIND, "schema_version": "1.0", "subject_ref": self.subject_ref, "producer_ref": self.producer_ref,
                "inputs": list(self.inputs), "revision": self.revision, "payload": thaw(self.payload)}
        identity = self.artifact_id or f"{self.KIND}:{canonical_hash(seed)[7:23]}"
        object.__setattr__(self, "artifact_id", identity)
        digest = canonical_hash({"artifact_id": identity} | seed)
        object.__setattr__(self, "content_hash", self.content_hash or digest)
        if self.content_hash != digest:
            raise ValueError("semantic artifact hash mismatch")

    def _body(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "kind": self.KIND, "schema_version": "1.0", "subject_ref": self.subject_ref,
                "producer_ref": self.producer_ref, "inputs": list(self.inputs), "revision": self.revision, "payload": thaw(self.payload)}

    def as_dict(self) -> dict[str, Any]:
        return self._body() | {"content_hash": self.content_hash}


def _typed(name: str, kind: str) -> type[TypedArtifact]:
    return type(name, (TypedArtifact,), {"KIND": kind})


ProjectContract = _typed("ProjectContract", "project.contract@1")
ProjectStructure = _typed("ProjectStructure", "project.structure@1")
WorkUnitContract = _typed("WorkUnitContract", "work_unit.contract@1")
InterfaceManifest = _typed("InterfaceManifest", "interface.manifest@1")
TestContract = _typed("TestContract", "test.contract@1")
TestResult = _typed("TestResult", "test.result@1")
FailureEvidence = _typed("FailureEvidence", "failure.evidence@1")
RepairDirective = _typed("RepairDirective", "repair.directive@1")
ProjectSnapshot = _typed("ProjectSnapshot", "project.snapshot@1")
AcceptanceReceipt = _typed("AcceptanceReceipt", "acceptance.receipt@1")
TYPES = {cls.KIND: cls for cls in (ProjectContract, ProjectStructure, WorkUnitContract, InterfaceManifest, TestContract, TestResult, FailureEvidence, RepairDirective, ProjectSnapshot, AcceptanceReceipt)}


class DesignAAdapter:
    design_id = "A"

    def create(self, kind: str, subject_ref: str, payload: Mapping[str, Any], *, producer_ref: str = "experiment", inputs: tuple[str, ...] = (), revision: int = 1) -> TypedArtifact:
        try:
            cls = TYPES[kind]
        except KeyError as exc:
            raise ValueError(f"unknown semantic artifact kind: {kind}") from exc
        return cls(subject_ref, payload, producer_ref, tuple(inputs), revision)

    def load(self, value: Mapping[str, Any]) -> TypedArtifact:
        if set(value) != {"artifact_id", "kind", "schema_version", "subject_ref", "producer_ref", "inputs", "revision", "payload", "content_hash"} or value.get("schema_version") != "1.0":
            raise ValueError("malformed typed artifact envelope")
        verify_content_hash(value)
        try:
            cls = TYPES[str(value["kind"])]
        except KeyError as exc:
            raise ValueError("unknown typed artifact") from exc
        return cls(str(value["subject_ref"]), dict(value["payload"]), str(value["producer_ref"]), tuple(str(item) for item in value["inputs"]), int(value["revision"]), str(value["artifact_id"]), str(value["content_hash"]))

    @staticmethod
    def as_dict(artifact: TypedArtifact) -> dict[str, Any]:
        return artifact.as_dict()

    def validate_graph(self, artifacts: tuple[TypedArtifact, ...], *, current_revisions: Mapping[str, int] | None = None) -> None:
        _validate_graph(artifacts, current_revisions)

    @staticmethod
    def complexity() -> Mapping[str, int]:
        return {"core_types": 11, "schema_count": 10}


def _validate_graph(artifacts: tuple[TypedArtifact, ...], current_revisions: Mapping[str, int] | None) -> None:
    by_id = {item.artifact_id: item for item in artifacts}
    if len(by_id) != len(artifacts):
        raise ValueError("duplicate artifact identity")
    for item in artifacts:
        if any(ref not in by_id for ref in item.inputs):
            raise ValueError("dangling artifact reference")
        if current_revisions and item.subject_ref in current_revisions and item.revision != current_revisions[item.subject_ref]:
            raise ValueError("stale semantic state")
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(identity: str) -> None:
        if identity in visiting: raise ValueError("cyclic artifact reference")
        if identity in visited: return
        visiting.add(identity)
        for ref in by_id[identity].inputs: visit(ref)
        visiting.remove(identity); visited.add(identity)
    for identity in by_id: visit(identity)


ADAPTER = DesignAAdapter()
