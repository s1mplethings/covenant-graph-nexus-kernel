"""Versioned contracts for the local-first Project Corpus.

The corpus records evaluation material.  It is deliberately separate from the
ProjectKnowledgePack, project state, and execution authorities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import pathlib
import re
from typing import Any, Mapping, Sequence


CORPUS_SCHEMA_VERSION = "1.0"
MANIFEST_SCHEMA_VERSION = "1.0"
BENCHMARK_MANIFEST_VERSION = "1.0"
DEFAULT_SPLIT_SEED = 5901


class SnapshotStage(str, Enum):
    INPUT = "INPUT"
    INITIAL_GENERATION = "INITIAL_GENERATION"
    POST_MATERIALIZATION = "POST_MATERIALIZATION"
    PRE_TEST = "PRE_TEST"
    FAILED_TEST = "FAILED_TEST"
    PRE_REPAIR = "PRE_REPAIR"
    POST_REPAIR = "POST_REPAIR"
    FINAL = "FINAL"
    ABORTED = "ABORTED"


class AttemptStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    ABORTED = "ABORTED"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    TIMEOUT = "TIMEOUT"
    QUARANTINED = "QUARANTINED"


class Provenance(str, Enum):
    GENERATED_ORIGINAL = "generated_original"
    THIRD_PARTY_SEEDED = "third_party_seeded"
    PUBLIC_REPO_DERIVED = "public_repo_derived"
    USER_SUPPLIED = "user_supplied"
    BENCHMARK_DERIVED = "benchmark_derived"
    UNKNOWN = "unknown"


class CorpusSplit(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    FORMAL_HOLDOUT = "FORMAL_HOLDOUT"
    QUARANTINE = "QUARANTINE"
    PUBLIC_SAMPLE = "PUBLIC_SAMPLE"


class ComplexityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return "sha256:" + sha256_bytes(canonical_json(value))


def validate_identifier(value: str, *, field_name: str) -> str:
    text = str(value)
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field_name} must be a safe stable identifier")
    return text


def normalize_project_path(value: str) -> str:
    raw = str(value).replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"project path must be relative: {value!r}")
    path = pathlib.PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"project path is unsafe: {value!r}")
    return path.as_posix()


def derive_complexity(metrics: Mapping[str, int]) -> str:
    """Derive a deterministic coarse label while retaining all raw metrics."""

    file_count = int(metrics.get("file_count", 0))
    loc = int(metrics.get("source_loc", 0)) + int(metrics.get("test_loc", 0))
    modules = int(metrics.get("module_count", 0))
    dependencies = int(metrics.get("dependency_count", 0))
    episodes = int(metrics.get("task_episode_count", 0))
    repairs = int(metrics.get("repair_rounds", 0))
    score = file_count + modules * 2 + dependencies * 2 + episodes * 3 + repairs * 4 + loc // 100
    if score <= 12:
        return ComplexityLevel.LOW.value
    if score <= 35:
        return ComplexityLevel.MEDIUM.value
    if score <= 80:
        return ComplexityLevel.HIGH.value
    return ComplexityLevel.EXTREME.value


@dataclass(frozen=True)
class FileRecord:
    path: str
    content_hash: str
    size: int
    mode: int = 0o644
    file_type: str = "source"
    language: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_project_path(self.path))
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_hash):
            raise ValueError("content_hash must be a sha256 digest")
        if self.size < 0:
            raise ValueError("file size cannot be negative")
        if self.mode < 0 or self.mode > 0o777:
            raise ValueError("file mode is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "size": self.size,
            "mode": self.mode,
            "file_type": self.file_type,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FileRecord":
        return cls(
            path=str(value["path"]),
            content_hash=str(value["content_hash"]),
            size=int(value["size"]),
            mode=int(value.get("mode", 0o644)),
            file_type=str(value.get("file_type", "source")),
            language=str(value.get("language", "")),
        )


@dataclass(frozen=True)
class SnapshotManifest:
    snapshot_id: str
    family_id: str
    attempt_id: str
    stage: str
    created_at: str
    files: tuple[FileRecord, ...]
    snapshot_hash: str = ""
    parent_snapshot_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_identifier(self.snapshot_id, field_name="snapshot_id")
        validate_identifier(self.family_id, field_name="family_id")
        validate_identifier(self.attempt_id, field_name="attempt_id")
        SnapshotStage(self.stage)
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("snapshot paths must be unique")
        expected = canonical_hash(self.as_dict(include_hash=False))
        if self.snapshot_hash and self.snapshot_hash != expected:
            raise ValueError("snapshot_hash does not match the manifest")
        object.__setattr__(self, "snapshot_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "kind": "CGNKProjectSnapshotManifest",
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "family_id": self.family_id,
            "attempt_id": self.attempt_id,
            "stage": self.stage,
            "created_at": self.created_at,
            "parent_snapshot_id": self.parent_snapshot_id or None,
            "files": [item.as_dict() for item in sorted(self.files, key=lambda item: item.path)],
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["snapshot_hash"] = self.snapshot_hash
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotManifest":
        if value.get("kind") != "CGNKProjectSnapshotManifest" or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported snapshot manifest")
        return cls(
            snapshot_id=str(value["snapshot_id"]),
            family_id=str(value["family_id"]),
            attempt_id=str(value["attempt_id"]),
            stage=str(value["stage"]),
            created_at=str(value["created_at"]),
            files=tuple(FileRecord.from_dict(item) for item in value.get("files", ())),
            snapshot_hash=str(value.get("snapshot_hash", "")),
            parent_snapshot_id=str(value.get("parent_snapshot_id") or ""),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class AttemptManifest:
    corpus_entry_id: str
    family_id: str
    attempt_id: str
    run_id: str
    created_at: str
    source_version: str
    generator_version: str
    task_hash: str
    status: str
    provenance: str
    split: str
    public_packet: Mapping[str, Any]
    snapshots: tuple[SnapshotManifest, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    lineage: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[Mapping[str, Any], ...] = ()
    tests: tuple[Mapping[str, Any], ...] = ()
    failures: tuple[Mapping[str, Any], ...] = ()
    repairs: tuple[Mapping[str, Any], ...] = ()
    private_evaluator_ref: str = ""
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("corpus_entry_id", self.corpus_entry_id),
            ("family_id", self.family_id),
            ("attempt_id", self.attempt_id),
            ("run_id", self.run_id),
        ):
            validate_identifier(value, field_name=name)
        AttemptStatus(self.status)
        Provenance(self.provenance)
        CorpusSplit(self.split)
        if any(item.family_id != self.family_id or item.attempt_id != self.attempt_id for item in self.snapshots):
            raise ValueError("snapshot lineage does not match the attempt")
        expected = canonical_hash(self.as_dict(include_hash=False))
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("manifest_hash does not match the attempt")
        object.__setattr__(self, "manifest_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "kind": "CGNKProjectCorpusEntry",
            "schema_version": CORPUS_SCHEMA_VERSION,
            "corpus_entry_id": self.corpus_entry_id,
            "project_family_id": self.family_id,
            "project_attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source_version": self.source_version,
            "generator_version": self.generator_version,
            "task_hash": self.task_hash,
            "status": self.status,
            "provenance": self.provenance,
            "split": self.split,
            "public_project_packet": dict(self.public_packet),
            "snapshot_refs": [
                {"snapshot_id": item.snapshot_id, "stage": item.stage, "snapshot_hash": item.snapshot_hash}
                for item in self.snapshots
            ],
            "metadata": dict(self.metadata),
            "lineage": dict(self.lineage),
            "events": [dict(item) for item in self.events],
            "tests": [dict(item) for item in self.tests],
            "failures": [dict(item) for item in self.failures],
            "repairs": [dict(item) for item in self.repairs],
            "private_evaluator_ref": self.private_evaluator_ref or None,
        }
        if include_hash:
            value["manifest_hash"] = self.manifest_hash
        return value

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        snapshots: Sequence[SnapshotManifest],
    ) -> "AttemptManifest":
        if value.get("kind") != "CGNKProjectCorpusEntry" or value.get("schema_version") != CORPUS_SCHEMA_VERSION:
            raise ValueError("unsupported corpus entry manifest")
        expected_refs = [
            {
                "snapshot_id": item.snapshot_id,
                "stage": item.stage,
                "snapshot_hash": item.snapshot_hash,
            }
            for item in snapshots
        ]
        if list(value.get("snapshot_refs") or ()) != expected_refs:
            raise ValueError("snapshot references do not match supplied manifests")
        return cls(
            corpus_entry_id=str(value["corpus_entry_id"]),
            family_id=str(value["project_family_id"]),
            attempt_id=str(value["project_attempt_id"]),
            run_id=str(value["run_id"]),
            created_at=str(value["created_at"]),
            source_version=str(value["source_version"]),
            generator_version=str(value["generator_version"]),
            task_hash=str(value["task_hash"]),
            status=str(value["status"]),
            provenance=str(value["provenance"]),
            split=str(value["split"]),
            public_packet=dict(value.get("public_project_packet") or {}),
            snapshots=tuple(snapshots),
            metadata=dict(value.get("metadata") or {}),
            lineage=dict(value.get("lineage") or {}),
            events=tuple(value.get("events") or ()),
            tests=tuple(value.get("tests") or ()),
            failures=tuple(value.get("failures") or ()),
            repairs=tuple(value.get("repairs") or ()),
            private_evaluator_ref=str(value.get("private_evaluator_ref") or ""),
            manifest_hash=str(value.get("manifest_hash") or ""),
        )


def build_benchmark_manifest(
    entries: Sequence[Mapping[str, Any]], *, seed: int, selection_rules: Mapping[str, Any]
) -> dict[str, Any]:
    body = {
        "kind": "CGNKProjectBenchmarkManifest",
        "schema_version": BENCHMARK_MANIFEST_VERSION,
        "seed": int(seed),
        "selection_rules": dict(selection_rules),
        "entries": [dict(item) for item in entries],
    }
    body["manifest_hash"] = canonical_hash(body)
    return body
