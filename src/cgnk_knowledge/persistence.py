from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


FORMAT_VERSION = "2.0"
MANIFEST_KIND = "ProjectKnowledgePersistenceManifest"
SEGMENT_KIND = "ProjectKnowledgeAuthoritySegment"
RECORD_KIND = "ProjectKnowledgeMutation"
CHECKPOINT_KIND = "ProjectKnowledgeCheckpoint"
ZERO_ROOT = "sha256:" + "0" * 64
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_SEGMENT_PATH = re.compile(r"^segments/seg-[0-9]{20}-[0-9]{20}-[0-9a-f]{16}\.json$")
_CHECKPOINT_PATH = re.compile(r"^checkpoints/checkpoint-[0-9]{20}-[0-9a-f]{16}\.json$")


class KnowledgePersistenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class PersistencePolicy:
    version: str = "1.0"
    checkpoint_mutation_interval: int = 256
    checkpoint_tail_bytes: int = 64 * 1024 * 1024
    compaction_segment_threshold: int = 64
    compaction_batch_size: int = 32
    compaction_tail_bytes: int = 32 * 1024 * 1024
    max_manifest_bytes: int = 8 * 1024 * 1024
    max_segment_bytes: int = 1024 * 1024 * 1024
    max_checkpoint_bytes: int = 1024 * 1024 * 1024
    max_record_bytes: int = 512 * 1024 * 1024

    def validate(self) -> None:
        values = asdict(self)
        for key, value in values.items():
            if key == "version":
                continue
            if not isinstance(value, int) or value <= 0:
                raise KnowledgePersistenceError("INVALID_PERSISTENCE_POLICY", f"{key} must be positive")
        if self.compaction_batch_size < 2:
            raise KnowledgePersistenceError("INVALID_PERSISTENCE_POLICY", "compaction_batch_size must be at least two")


DEFAULT_POLICY = PersistencePolicy()
FailureInjector = Callable[[str], None]


class KnowledgePersistenceBackend(Protocol):
    """Physical persistence boundary behind ProjectKnowledgePack semantics."""

    def load(self, *, use_checkpoint: bool = True, as_of_sequence: int | None = None) -> Mapping[str, Any]: ...
    def commit_mutations(self, mutations: Sequence[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]: ...
    def create_checkpoint(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def compact(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def verify(self) -> Mapping[str, Any]: ...


class TrackedKnowledgePack(dict[str, Any]):
    """A normal dict with non-serialized persistence coordination metadata."""

    _persistence_root: str | None
    _persistence_sequence: int
    _persistence_authority_root: str
    _pending_mutations: list[dict[str, Any]]
    _load_receipt: dict[str, Any]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._persistence_root = None
        self._persistence_sequence = 0
        self._persistence_authority_root = ZERO_ROOT
        self._pending_mutations = []
        self._load_receipt = {}


def tracked_pack(
    value: Mapping[str, Any], *, root: pathlib.Path | None = None, sequence: int = 0,
    authority_root: str = ZERO_ROOT, load_receipt: Mapping[str, Any] | None = None,
) -> TrackedKnowledgePack:
    pack = TrackedKnowledgePack(value)
    pack._persistence_root = str(root.resolve()) if root else None
    pack._persistence_sequence = sequence
    pack._persistence_authority_root = authority_root
    pack._load_receipt = dict(load_receipt or {})
    return pack


def clone_pack(value: Mapping[str, Any]) -> TrackedKnowledgePack:
    pack = tracked_pack(
        value,
        root=pathlib.Path(value._persistence_root) if isinstance(value, TrackedKnowledgePack) and value._persistence_root else None,
        sequence=value._persistence_sequence if isinstance(value, TrackedKnowledgePack) else 0,
        authority_root=value._persistence_authority_root if isinstance(value, TrackedKnowledgePack) else ZERO_ROOT,
        load_receipt=value._load_receipt if isinstance(value, TrackedKnowledgePack) else None,
    )
    if isinstance(value, TrackedKnowledgePack):
        pack._pending_mutations = copy.deepcopy(value._pending_mutations)
    return pack


def attach_pending_mutation(pack: Mapping[str, Any], mutation: Mapping[str, Any] | None) -> None:
    if mutation and isinstance(pack, TrackedKnowledgePack):
        pack._pending_mutations.append(copy.deepcopy(dict(mutation)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _value_hash(value: Any) -> str:
    return _sha256(_json_bytes(value))


def _document_bytes(payload: Mapping[str, Any]) -> bytes:
    value = dict(payload)
    return _json_bytes({"payload": value, "checksum": _value_hash(value)})


def _read_bytes(path: pathlib.Path, maximum: int, code: str) -> bytes:
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise KnowledgePersistenceError("MISSING_PERSISTENCE_FILE", str(path)) from exc
    if size > maximum:
        raise KnowledgePersistenceError(code, f"{path.name} is {size} bytes")
    return path.read_bytes()


def _parse_json(raw: bytes, *, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgePersistenceError("MALFORMED_PERSISTENCE_DOCUMENT", label) from exc


def _read_document(path: pathlib.Path, maximum: int) -> tuple[dict[str, Any], bytes]:
    raw = _read_bytes(path, maximum, "PERSISTENCE_DOCUMENT_TOO_LARGE")
    document = _parse_json(raw, label=str(path))
    if not isinstance(document, dict) or set(document) != {"payload", "checksum"} or not isinstance(document["payload"], dict):
        raise KnowledgePersistenceError("INVALID_PERSISTENCE_DOCUMENT", str(path))
    if document["checksum"] != _value_hash(document["payload"]):
        raise KnowledgePersistenceError("PERSISTENCE_CHECKSUM_MISMATCH", str(path))
    return dict(document["payload"]), raw


def _fsync_directory(path: pathlib.Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _inject(injector: FailureInjector | None, point: str) -> None:
    if injector is not None:
        injector(point)


def _atomic_write(
    path: pathlib.Path, data: bytes, *, before: str, during: str, before_replace: str,
    after_replace: str, injector: FailureInjector | None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    _inject(injector, before)
    try:
        with temporary.open("xb") as handle:
            split = max(1, len(data) // 2)
            handle.write(data[:split])
            handle.flush()
            _inject(injector, during)
            handle.write(data[split:])
            handle.flush()
            os.fsync(handle.fileno())
        _inject(injector, before_replace)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        _inject(injector, after_replace)
    except Exception:
        # An interrupted temporary file is intentionally left for deterministic
        # orphan inspection. It is never referenced by the committed manifest.
        raise
    return len(data)


class _WriteLock:
    def __init__(self, root: pathlib.Path) -> None:
        self.path = root / ".write.lock"
        self.handle: Any = None

    def __enter__(self) -> "_WriteLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise KnowledgePersistenceError("PACK_WRITE_LOCKED", str(self.path)) from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


def authoritative_projection(pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(pack.get("kind", "ProjectKnowledgePack")),
        "id": str(pack.get("id", "")),
        "project": str(pack.get("project", "")),
        "version": str(pack.get("version", "1")),
        "knowledge_revision": int(pack.get("knowledge_revision", 0)),
        "diagnostics": copy.deepcopy(list(pack.get("diagnostics", ()))),
        "all_items": copy.deepcopy(list(pack.get("all_items", ()))),
    }


def _semantic_projection(pack: Mapping[str, Any]) -> dict[str, Any]:
    projection = authoritative_projection(pack)
    projection["all_items"] = sorted(projection["all_items"], key=lambda row: str(row.get("id", "")))
    return projection


def project_knowledge_semantic_hash(pack: Mapping[str, Any]) -> str:
    return _value_hash(_semantic_projection(pack))


def build_pack_mutation(
    pack: Mapping[str, Any], changed_item_ids: Iterable[str], *, operation_kind: str,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    by_id = {str(row.get("id")): row for row in pack.get("all_items", ())}
    item_ids = sorted(set(map(str, changed_item_ids)))
    missing = [item_id for item_id in item_ids if item_id not in by_id]
    if missing:
        raise KnowledgePersistenceError("MUTATION_ITEM_MISSING", ",".join(missing))
    return {
        "operation": operation_kind,
        "target_identity": str(pack.get("id", "")),
        "target_item_ids": item_ids,
        "payload": {
            "metadata": {
                "kind": str(pack.get("kind", "ProjectKnowledgePack")),
                "id": str(pack.get("id", "")),
                "project": str(pack.get("project", "")),
                "version": str(pack.get("version", "1")),
                "knowledge_revision": int(pack.get("knowledge_revision", 0)),
                "diagnostics": copy.deepcopy(list(pack.get("diagnostics", ()))),
            },
            "items": [copy.deepcopy(by_id[item_id]) for item_id in item_ids],
        },
        "provenance": {
            "source_refs": sorted({str(ref) for item_id in item_ids for ref in by_id[item_id].get("source_refs", ())}),
            **{str(key): copy.deepcopy(value) for key, value in (provenance or {}).items() if key in {"relation", "policy", "reason"}},
        },
    }


def _record(mutation: Mapping[str, Any], sequence: int, policy: PersistencePolicy) -> dict[str, Any]:
    core = {
        "kind": RECORD_KIND,
        "format_version": FORMAT_VERSION,
        "sequence": sequence,
        "operation": str(mutation.get("operation", "UPSERT_ITEMS")),
        "target_identity": str(mutation.get("target_identity", "")),
        "target_item_ids": list(map(str, mutation.get("target_item_ids", ()))),
        "payload": copy.deepcopy(dict(mutation.get("payload", {}))),
        "provenance": copy.deepcopy(dict(mutation.get("provenance", {}))),
    }
    if core["operation"] not in {"INITIALIZE", "UPSERT_ITEMS", "ARCHIVE", "DISCARD", "REFRESH"}:
        raise KnowledgePersistenceError("UNKNOWN_MUTATION_OPERATION", core["operation"])
    if not _SAFE_ID.fullmatch(core["target_identity"]):
        raise KnowledgePersistenceError("INVALID_PACK_ID", core["target_identity"])
    encoded = _json_bytes(core)
    if len(encoded) > policy.max_record_bytes:
        raise KnowledgePersistenceError("PERSISTENCE_RECORD_TOO_LARGE", str(len(encoded)))
    return {**core, "record_hash": _sha256(encoded)}


def _next_root(previous: str, record_hash: str) -> str:
    return _sha256(f"{previous}|{record_hash}".encode("ascii"))


def _build_segment(pack_id: str, records: Sequence[Mapping[str, Any]], previous_root: str) -> tuple[dict[str, Any], str]:
    if not records:
        raise KnowledgePersistenceError("EMPTY_AUTHORITY_SEGMENT", pack_id)
    sequences = [int(row["sequence"]) for row in records]
    if sequences != list(range(sequences[0], sequences[-1] + 1)):
        raise KnowledgePersistenceError("AUTHORITY_SEQUENCE_GAP", str(sequences))
    root = previous_root
    for row in records:
        core = {key: copy.deepcopy(value) for key, value in row.items() if key != "record_hash"}
        if row.get("record_hash") != _sha256(_json_bytes(core)):
            raise KnowledgePersistenceError("MUTATION_CHECKSUM_MISMATCH", str(row.get("sequence")))
        root = _next_root(root, str(row["record_hash"]))
    digest = hashlib.sha256("|".join(str(row["record_hash"]) for row in records).encode("ascii")).hexdigest()[:16]
    segment_id = f"seg-{sequences[0]:020d}-{sequences[-1]:020d}-{digest}"
    core = {
        "kind": SEGMENT_KIND,
        "format_version": FORMAT_VERSION,
        "segment_id": segment_id,
        "pack_id": pack_id,
        "sequence_start": sequences[0],
        "sequence_end": sequences[-1],
        "record_count": len(records),
        "previous_authority_root_hash": previous_root,
        "authority_root_hash": root,
        "records": [copy.deepcopy(dict(row)) for row in records],
    }
    return {**core, "content_checksum": _value_hash(core)}, f"segments/{segment_id}.json"


def _segment_descriptor(segment: Mapping[str, Any], path: str, raw: bytes) -> dict[str, Any]:
    return {
        "segment_id": str(segment["segment_id"]),
        "path": path,
        "sequence_start": int(segment["sequence_start"]),
        "sequence_end": int(segment["sequence_end"]),
        "record_count": int(segment["record_count"]),
        "previous_authority_root_hash": str(segment["previous_authority_root_hash"]),
        "authority_root_hash": str(segment["authority_root_hash"]),
        "content_checksum": str(segment["content_checksum"]),
        "file_hash": _sha256(raw),
        "file_bytes": len(raw),
    }


def _manifest_checksum_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in manifest.items() if key != "manifest_checksum"}


def _finalize_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    core = _manifest_checksum_payload(manifest)
    return {**core, "manifest_checksum": _value_hash(core)}


def _validate_descriptor_chain(manifest: Mapping[str, Any]) -> None:
    segments = list(manifest.get("authoritative_segments", ()))
    if not segments:
        raise KnowledgePersistenceError("EMPTY_AUTHORITY", str(manifest.get("pack_id", "")))
    expected_sequence = 1
    expected_root = ZERO_ROOT
    seen: set[int] = set()
    for descriptor in segments:
        path = str(descriptor.get("path", ""))
        if not _SEGMENT_PATH.fullmatch(path):
            raise KnowledgePersistenceError("UNSAFE_SEGMENT_PATH", path)
        start, end = int(descriptor.get("sequence_start", -1)), int(descriptor.get("sequence_end", -1))
        if start != expected_sequence or end < start:
            raise KnowledgePersistenceError("AUTHORITY_SEQUENCE_GAP", f"expected {expected_sequence}, got {start}-{end}")
        for sequence in range(start, end + 1):
            if sequence in seen:
                raise KnowledgePersistenceError("DUPLICATE_AUTHORITY_SEQUENCE", str(sequence))
            seen.add(sequence)
        if descriptor.get("previous_authority_root_hash") != expected_root:
            raise KnowledgePersistenceError("AUTHORITY_CHAIN_MISMATCH", str(descriptor.get("segment_id", "")))
        expected_root = str(descriptor.get("authority_root_hash", ""))
        expected_sequence = end + 1
    if int(manifest.get("first_sequence", 0)) != 1 or int(manifest.get("latest_sequence", -1)) != expected_sequence - 1:
        raise KnowledgePersistenceError("MANIFEST_SEQUENCE_MISMATCH", str(manifest.get("latest_sequence")))
    if manifest.get("authority_root_hash") != expected_root:
        raise KnowledgePersistenceError("MANIFEST_AUTHORITY_ROOT_MISMATCH", str(manifest.get("authority_root_hash")))


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("kind") != MANIFEST_KIND or manifest.get("format_version") != FORMAT_VERSION:
        raise KnowledgePersistenceError("UNSUPPORTED_PERSISTENCE_FORMAT", str(manifest.get("format_version")))
    if not _SAFE_ID.fullmatch(str(manifest.get("pack_id", ""))):
        raise KnowledgePersistenceError("INVALID_PACK_ID", str(manifest.get("pack_id", "")))
    if manifest.get("manifest_checksum") != _value_hash(_manifest_checksum_payload(manifest)):
        raise KnowledgePersistenceError("MANIFEST_CHECKSUM_MISMATCH", str(manifest.get("pack_id", "")))
    _validate_descriptor_chain(manifest)
    checkpoint = manifest.get("current_checkpoint")
    if checkpoint is not None:
        if not isinstance(checkpoint, dict) or not _CHECKPOINT_PATH.fullmatch(str(checkpoint.get("path", ""))):
            raise KnowledgePersistenceError("UNSAFE_CHECKPOINT_PATH", str(checkpoint))
        covered = int(checkpoint.get("covered_sequence", -1))
        matches = [row for row in manifest["authoritative_segments"] if int(row["sequence_end"]) == covered]
        if len(matches) != 1 or matches[0]["authority_root_hash"] != checkpoint.get("authority_root_hash"):
            raise KnowledgePersistenceError("CHECKPOINT_AUTHORITY_PREFIX_MISMATCH", str(covered))


def _materialize(projection: Mapping[str, Any], cached_index: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from .store import rebuild_pack_buckets, rebuild_pack_indexes

    pack = dict(copy.deepcopy(projection))
    pack["knowledge_index"] = copy.deepcopy(dict(cached_index or {}))
    if cached_index:
        return rebuild_pack_buckets(pack, sort_all_items=False)
    return rebuild_pack_indexes(pack)


def _apply_record(projection: dict[str, Any] | None, record: Mapping[str, Any], pack_id: str) -> dict[str, Any]:
    if str(record.get("target_identity", "")) != pack_id:
        raise KnowledgePersistenceError("CROSS_PACK_RECORD", str(record.get("target_identity", "")))
    operation = str(record.get("operation", ""))
    payload = dict(record.get("payload", {}))
    if operation == "INITIALIZE":
        if projection is not None:
            raise KnowledgePersistenceError("DUPLICATE_INITIALIZE_RECORD", pack_id)
        authority = payload.get("authority")
        if not isinstance(authority, dict) or authority.get("id") != pack_id:
            raise KnowledgePersistenceError("INVALID_INITIAL_AUTHORITY", pack_id)
        return copy.deepcopy(dict(authority))
    if projection is None:
        raise KnowledgePersistenceError("MISSING_INITIALIZE_RECORD", pack_id)
    metadata = payload.get("metadata")
    items = payload.get("items")
    if not isinstance(metadata, dict) or not isinstance(items, list) or metadata.get("id") != pack_id:
        raise KnowledgePersistenceError("INVALID_MUTATION_PAYLOAD", str(record.get("sequence")))
    by_id = {str(row.get("id")): index for index, row in enumerate(projection.get("all_items", ())) if row.get("id")}
    all_items = list(projection.get("all_items", ()))
    for item in items:
        if not isinstance(item, dict) or not str(item.get("id", "")):
            raise KnowledgePersistenceError("INVALID_MUTATION_ITEM", str(record.get("sequence")))
        item_id = str(item["id"])
        if item_id in by_id:
            all_items[by_id[item_id]] = copy.deepcopy(item)
        else:
            by_id[item_id] = len(all_items)
            all_items.append(copy.deepcopy(item))
    projection.update({key: copy.deepcopy(value) for key, value in metadata.items()})
    projection["all_items"] = all_items
    return projection


def _apply_record_to_materialized(pack: dict[str, Any], record: Mapping[str, Any], pack_id: str) -> None:
    """Apply a tail record without rebuilding the checkpoint's global index."""
    from .internalization import _append_index, _replace_index_content, _sync_buckets

    if str(record.get("target_identity", "")) != pack_id or record.get("operation") == "INITIALIZE":
        raise KnowledgePersistenceError("INVALID_CHECKPOINT_TAIL_RECORD", str(record.get("sequence", "")))
    payload = dict(record.get("payload", {}))
    metadata, items = payload.get("metadata"), payload.get("items")
    if not isinstance(metadata, dict) or not isinstance(items, list) or metadata.get("id") != pack_id:
        raise KnowledgePersistenceError("INVALID_MUTATION_PAYLOAD", str(record.get("sequence", "")))
    index = pack["knowledge_index"]
    all_items = pack["all_items"]
    changed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not str(item.get("id", "")):
            raise KnowledgePersistenceError("INVALID_MUTATION_ITEM", str(record.get("sequence", "")))
        value = copy.deepcopy(item)
        item_id = str(value["id"])
        if item_id in index.get("by_id", {}):
            position = int(index["by_id"][item_id])
            old = all_items[position]
            all_items[position] = value
            _replace_index_content(index, old, value)
        else:
            position = len(all_items)
            all_items.append(value)
            _append_index(index, value, position)
        changed[item_id] = value
    pack.update({key: copy.deepcopy(value) for key, value in metadata.items()})
    pack["all_items"] = all_items
    index["pack_revision"] = int(pack.get("knowledge_revision", 0))
    index["item_count"] = len(all_items)
    _sync_buckets(pack, index, changed)


class SegmentedKnowledgeStore:
    def __init__(self, root: str | pathlib.Path, *, policy: PersistencePolicy = DEFAULT_POLICY) -> None:
        policy.validate()
        self.root = pathlib.Path(root)
        self.policy = policy
        self.manifest_path = self.root / "manifest.json"

    def _manifest(self) -> dict[str, Any]:
        payload, _ = _read_document(self.manifest_path, self.policy.max_manifest_bytes)
        _validate_manifest(payload)
        return payload

    def _write_manifest(self, manifest: Mapping[str, Any], injector: FailureInjector | None = None) -> int:
        value = _finalize_manifest(manifest)
        _validate_manifest(value)
        return _atomic_write(
            self.manifest_path, _document_bytes(value), before="C4_BEFORE_MANIFEST_WRITE",
            during="C4_DURING_MANIFEST_WRITE", before_replace="C5_BEFORE_MANIFEST_REPLACE",
            after_replace="C6_AFTER_MANIFEST_REPLACE", injector=injector,
        )

    def _write_segment(
        self, segment: Mapping[str, Any], relative: str, injector: FailureInjector | None = None,
        *, compaction: bool = False,
    ) -> tuple[dict[str, Any], int]:
        if not _SEGMENT_PATH.fullmatch(relative):
            raise KnowledgePersistenceError("UNSAFE_SEGMENT_PATH", relative)
        raw = _json_bytes(segment)
        if len(raw) > self.policy.max_segment_bytes:
            raise KnowledgePersistenceError("AUTHORITY_SEGMENT_TOO_LARGE", str(len(raw)))
        path = self.root / relative
        written = _atomic_write(
            path, raw, before="C1_BEFORE_SEGMENT_WRITE", during="C2_DURING_SEGMENT_WRITE",
            before_replace="C2_BEFORE_SEGMENT_REPLACE", after_replace="C8_DURING_COMPACTION" if compaction else "C3_SEGMENT_COMPLETE_BEFORE_MANIFEST",
            injector=injector,
        )
        parsed = _parse_json(path.read_bytes(), label=str(path))
        self._validate_segment(parsed, expected_pack_id=str(segment["pack_id"]))
        return _segment_descriptor(parsed, relative, raw), written

    def _validate_segment(self, segment: Mapping[str, Any], *, expected_pack_id: str) -> None:
        if segment.get("kind") != SEGMENT_KIND or segment.get("format_version") != FORMAT_VERSION:
            raise KnowledgePersistenceError("INVALID_AUTHORITY_SEGMENT", str(segment.get("segment_id", "")))
        if segment.get("pack_id") != expected_pack_id:
            raise KnowledgePersistenceError("CROSS_PACK_SEGMENT", str(segment.get("pack_id", "")))
        core = {key: copy.deepcopy(value) for key, value in segment.items() if key != "content_checksum"}
        if segment.get("content_checksum") != _value_hash(core):
            raise KnowledgePersistenceError("SEGMENT_CHECKSUM_MISMATCH", str(segment.get("segment_id", "")))
        records = list(segment.get("records", ()))
        if int(segment.get("record_count", -1)) != len(records) or not records:
            raise KnowledgePersistenceError("SEGMENT_RECORD_COUNT_MISMATCH", str(segment.get("segment_id", "")))
        rebuilt, _ = _build_segment(expected_pack_id, records, str(segment.get("previous_authority_root_hash", "")))
        for key in ("segment_id", "sequence_start", "sequence_end", "authority_root_hash", "content_checksum"):
            if rebuilt[key] != segment.get(key):
                raise KnowledgePersistenceError("SEGMENT_INTEGRITY_MISMATCH", f"{segment.get('segment_id')}:{key}")

    def _read_segment(self, descriptor: Mapping[str, Any], pack_id: str) -> dict[str, Any]:
        relative = str(descriptor.get("path", ""))
        if not _SEGMENT_PATH.fullmatch(relative):
            raise KnowledgePersistenceError("UNSAFE_SEGMENT_PATH", relative)
        raw = _read_bytes(self.root / relative, self.policy.max_segment_bytes, "AUTHORITY_SEGMENT_TOO_LARGE")
        if _sha256(raw) != descriptor.get("file_hash"):
            raise KnowledgePersistenceError("SEGMENT_FILE_HASH_MISMATCH", relative)
        segment = _parse_json(raw, label=relative)
        if not isinstance(segment, dict):
            raise KnowledgePersistenceError("INVALID_AUTHORITY_SEGMENT", relative)
        self._validate_segment(segment, expected_pack_id=pack_id)
        for key in (
            "segment_id", "sequence_start", "sequence_end", "record_count",
            "previous_authority_root_hash", "authority_root_hash", "content_checksum",
        ):
            if segment.get(key) != descriptor.get(key):
                raise KnowledgePersistenceError("SEGMENT_DESCRIPTOR_MISMATCH", f"{relative}:{key}")
        return dict(segment)

    def initialize(self, pack: Mapping[str, Any], *, injector: FailureInjector | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        pack_id = str(pack.get("id", ""))
        if not _SAFE_ID.fullmatch(pack_id):
            raise KnowledgePersistenceError("INVALID_PACK_ID", pack_id)
        self.root.mkdir(parents=True, exist_ok=True)
        with _WriteLock(self.root):
            if self.manifest_path.exists():
                raise KnowledgePersistenceError("PACK_ALREADY_INITIALIZED", str(self.root))
            mutation = {
                "operation": "INITIALIZE", "target_identity": pack_id, "target_item_ids": [],
                "payload": {"authority": authoritative_projection(pack)}, "provenance": {"source_refs": []},
            }
            record = _record(mutation, 1, self.policy)
            segment, relative = _build_segment(pack_id, [record], ZERO_ROOT)
            descriptor, segment_bytes = self._write_segment(segment, relative, injector)
            now = _utc_now()
            manifest = {
                "kind": MANIFEST_KIND, "format_version": FORMAT_VERSION, "pack_id": pack_id,
                "generation": 1, "schema_version": str(pack.get("version", "1")),
                "first_sequence": 1, "latest_sequence": 1,
                "authoritative_segments": [descriptor], "current_checkpoint": None,
                "checkpoint_covered_sequence": 0, "authority_root_hash": segment["authority_root_hash"],
                "segment_policy_version": self.policy.version, "compaction_policy_version": self.policy.version,
                "created_at": now, "updated_at": now,
            }
            manifest_bytes = self._write_manifest(manifest, injector)
        return {
            "kind": "KnowledgeStoreWriteResult", "format_version": FORMAT_VERSION,
            "path": str(self.root), "sequence_start": 1, "sequence_end": 1,
            "authority_root_hash": segment["authority_root_hash"], "authoritative_bytes_written": segment_bytes,
            "manifest_bytes_written": manifest_bytes, "total_physical_bytes_written": segment_bytes + manifest_bytes,
            "fsync_count": 2 + (0 if os.name == "nt" else 2), "file_operations": 4,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "checkpoint_due": False, "compaction_due": False, "diagnostics": [],
        }

    def commit_mutations(
        self, mutations: Sequence[Mapping[str, Any]], *, expected_sequence: int | None = None,
        expected_authority_root: str | None = None, injector: FailureInjector | None = None,
    ) -> dict[str, Any]:
        if not mutations:
            return {"kind": "KnowledgeStoreWriteResult", "format_version": FORMAT_VERSION, "path": str(self.root), "no_op": True, "diagnostics": []}
        started = time.perf_counter()
        with _WriteLock(self.root):
            manifest = self._manifest()
            if expected_sequence is not None and int(manifest["latest_sequence"]) != expected_sequence:
                raise KnowledgePersistenceError("PACK_SEQUENCE_CONFLICT", f"expected {expected_sequence}, found {manifest['latest_sequence']}")
            if expected_authority_root is not None and manifest["authority_root_hash"] != expected_authority_root:
                raise KnowledgePersistenceError("PACK_AUTHORITY_CONFLICT", str(expected_authority_root))
            first = int(manifest["latest_sequence"]) + 1
            records = [_record(mutation, first + offset, self.policy) for offset, mutation in enumerate(mutations)]
            segment, relative = _build_segment(str(manifest["pack_id"]), records, str(manifest["authority_root_hash"]))
            descriptor, segment_bytes = self._write_segment(segment, relative, injector)
            updated = dict(manifest)
            updated.update({
                "generation": int(manifest["generation"]) + 1,
                "latest_sequence": int(segment["sequence_end"]),
                "authoritative_segments": [*manifest["authoritative_segments"], descriptor],
                "authority_root_hash": segment["authority_root_hash"], "updated_at": _utc_now(),
            })
            manifest_bytes = self._write_manifest(updated, injector)
            tail_segments, tail_bytes = self._tail_since_checkpoint(updated)
        return {
            "kind": "KnowledgeStoreWriteResult", "format_version": FORMAT_VERSION, "path": str(self.root),
            "sequence_start": first, "sequence_end": int(segment["sequence_end"]),
            "authority_root_hash": segment["authority_root_hash"], "authoritative_bytes_written": segment_bytes,
            "manifest_bytes_written": manifest_bytes, "checkpoint_bytes_written": 0, "compaction_bytes_written": 0,
            "total_physical_bytes_written": segment_bytes + manifest_bytes,
            "fsync_count": 2 + (0 if os.name == "nt" else 2), "file_operations": 4,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "checkpoint_due": tail_segments >= self.policy.checkpoint_mutation_interval or tail_bytes >= self.policy.checkpoint_tail_bytes,
            "compaction_due": len(updated["authoritative_segments"]) >= self.policy.compaction_segment_threshold or tail_bytes >= self.policy.compaction_tail_bytes,
            "diagnostics": [],
        }

    @staticmethod
    def _tail_since_checkpoint(manifest: Mapping[str, Any]) -> tuple[int, int]:
        covered = int(manifest.get("checkpoint_covered_sequence", 0))
        rows = [row for row in manifest["authoritative_segments"] if int(row["sequence_end"]) > covered]
        return sum(int(row["record_count"]) for row in rows), sum(int(row["file_bytes"]) for row in rows)

    def _validated_segment_descriptors(self, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for descriptor in manifest["authoritative_segments"]:
            relative = str(descriptor["path"])
            raw = _read_bytes(self.root / relative, self.policy.max_segment_bytes, "AUTHORITY_SEGMENT_TOO_LARGE")
            if _sha256(raw) != descriptor.get("file_hash"):
                raise KnowledgePersistenceError("SEGMENT_FILE_HASH_MISMATCH", relative)
            rows.append(dict(descriptor))
        return rows

    def _replay(self, manifest: Mapping[str, Any], *, start_after: int = 0, initial: Mapping[str, Any] | None = None,
                stop_at: int | None = None) -> dict[str, Any]:
        projection = copy.deepcopy(dict(initial)) if initial is not None else None
        pack_id = str(manifest["pack_id"])
        expected = start_after + 1
        for descriptor in manifest["authoritative_segments"]:
            if int(descriptor["sequence_end"]) <= start_after:
                continue
            segment = self._read_segment(descriptor, pack_id)
            for record in segment["records"]:
                sequence = int(record["sequence"])
                if sequence <= start_after:
                    continue
                if stop_at is not None and sequence > stop_at:
                    break
                if sequence != expected:
                    raise KnowledgePersistenceError("AUTHORITY_SEQUENCE_GAP", f"expected {expected}, got {sequence}")
                projection = _apply_record(projection, record, pack_id)
                expected += 1
            if stop_at is not None and expected > stop_at:
                break
        target = stop_at if stop_at is not None else int(manifest["latest_sequence"])
        if projection is None or expected - 1 != target:
            raise KnowledgePersistenceError("AUTHORITY_REPLAY_INCOMPLETE", f"expected through {target}, got {expected - 1}")
        return projection

    def _read_checkpoint(self, manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        descriptor = manifest.get("current_checkpoint")
        if not isinstance(descriptor, dict):
            raise KnowledgePersistenceError("CHECKPOINT_MISSING", str(self.root))
        relative = str(descriptor.get("path", ""))
        if not _CHECKPOINT_PATH.fullmatch(relative):
            raise KnowledgePersistenceError("UNSAFE_CHECKPOINT_PATH", relative)
        payload, raw = _read_document(self.root / relative, self.policy.max_checkpoint_bytes)
        if _sha256(raw) != descriptor.get("file_hash"):
            raise KnowledgePersistenceError("CHECKPOINT_FILE_HASH_MISMATCH", relative)
        if payload.get("kind") != CHECKPOINT_KIND or payload.get("format_version") != FORMAT_VERSION:
            raise KnowledgePersistenceError("INVALID_CHECKPOINT", relative)
        for key in ("checkpoint_id", "covered_sequence", "authority_root_hash", "logical_state_hash", "index_hash"):
            if payload.get(key) != descriptor.get(key):
                raise KnowledgePersistenceError("CHECKPOINT_DESCRIPTOR_MISMATCH", f"{relative}:{key}")
        if payload.get("pack_id") != manifest.get("pack_id"):
            raise KnowledgePersistenceError("CROSS_PACK_CHECKPOINT", relative)
        authority = payload.get("authority")
        index = payload.get("knowledge_index")
        if not isinstance(authority, dict) or not isinstance(index, dict):
            raise KnowledgePersistenceError("INVALID_CHECKPOINT", relative)
        if project_knowledge_semantic_hash(authority) != payload.get("logical_state_hash"):
            raise KnowledgePersistenceError("CHECKPOINT_STATE_HASH_MISMATCH", relative)
        if _value_hash(index) != payload.get("index_hash"):
            raise KnowledgePersistenceError("CHECKPOINT_INDEX_HASH_MISMATCH", relative)
        return dict(authority), dict(index)

    def load(self, *, use_checkpoint: bool = True, as_of_sequence: int | None = None) -> TrackedKnowledgePack:
        started = time.perf_counter()
        phase = time.perf_counter()
        manifest = self._manifest()
        manifest_read_ms = (time.perf_counter() - phase) * 1000
        phase = time.perf_counter()
        self._validated_segment_descriptors(manifest)
        segment_validation_ms = (time.perf_counter() - phase) * 1000
        latest = int(manifest["latest_sequence"])
        target = latest if as_of_sequence is None else int(as_of_sequence)
        if target < 1 or target > latest:
            raise KnowledgePersistenceError("INVALID_AS_OF_SEQUENCE", str(target))
        checkpoint_status = "NOT_USED"
        projection: dict[str, Any]
        cached_index: dict[str, Any] | None = None
        materialized: dict[str, Any] | None = None
        start_after = 0
        checkpoint_load_ms = 0.0
        index_materialization_ms = 0.0
        if use_checkpoint and manifest.get("current_checkpoint") and int(manifest.get("checkpoint_covered_sequence", 0)) <= target:
            phase = time.perf_counter()
            try:
                projection, cached_index = self._read_checkpoint(manifest)
                start_after = int(manifest["checkpoint_covered_sequence"])
                checkpoint_status = "VALID_USED"
                materialize_started = time.perf_counter()
                materialized = _materialize(projection, cached_index)
                index_materialization_ms = (time.perf_counter() - materialize_started) * 1000
            except KnowledgePersistenceError as exc:
                projection = {}
                cached_index = None
                materialized = None
                start_after = 0
                checkpoint_status = f"REJECTED_REPLAYED:{exc.code}"
            checkpoint_load_ms = (time.perf_counter() - phase) * 1000
        phase = time.perf_counter()
        if start_after < target:
            if materialized is not None:
                expected = start_after + 1
                for descriptor in manifest["authoritative_segments"]:
                    if int(descriptor["sequence_end"]) <= start_after:
                        continue
                    segment = self._read_segment(descriptor, str(manifest["pack_id"]))
                    for record in segment["records"]:
                        sequence = int(record["sequence"])
                        if sequence <= start_after:
                            continue
                        if sequence > target:
                            break
                        if sequence != expected:
                            raise KnowledgePersistenceError("AUTHORITY_SEQUENCE_GAP", f"expected {expected}, got {sequence}")
                        _apply_record_to_materialized(materialized, record, str(manifest["pack_id"]))
                        expected += 1
                if expected - 1 != target:
                    raise KnowledgePersistenceError("AUTHORITY_REPLAY_INCOMPLETE", f"expected through {target}, got {expected - 1}")
            else:
                projection = self._replay(manifest, start_after=0, initial=None, stop_at=target)
        tail_replay_ms = (time.perf_counter() - phase) * 1000
        if materialized is None:
            phase = time.perf_counter()
            materialized = _materialize(projection, None)
            index_materialization_ms = (time.perf_counter() - phase) * 1000
        pack = materialized
        semantic_hash = project_knowledge_semantic_hash(pack)
        receipt = {
            "kind": "KnowledgeStoreLoadReceipt", "format_version": FORMAT_VERSION,
            "path": str(self.root), "sequence": target, "authority_root_hash": manifest["authority_root_hash"] if target == latest else None,
            "semantic_hash": semantic_hash, "checkpoint_status": checkpoint_status,
            "segments_validated": len(manifest["authoritative_segments"]),
            "manifest_read_ms": round(manifest_read_ms, 3),
            "segment_validation_ms": round(segment_validation_ms, 3),
            "checkpoint_load_ms": round(checkpoint_load_ms, 3),
            "tail_replay_ms": round(tail_replay_ms, 3),
            "index_materialization_ms": round(index_materialization_ms, 3),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        return tracked_pack(pack, root=self.root, sequence=target,
                            authority_root=str(manifest["authority_root_hash"]) if target == latest else ZERO_ROOT,
                            load_receipt=receipt)

    def create_checkpoint(self, *, injector: FailureInjector | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        with _WriteLock(self.root):
            manifest = self._manifest()
            pack = self.load(use_checkpoint=False)
            semantic_hash = project_knowledge_semantic_hash(pack)
            authority = authoritative_projection(pack)
            replay_hash = project_knowledge_semantic_hash(authority)
            if semantic_hash != replay_hash:
                raise KnowledgePersistenceError("CHECKPOINT_FIDELITY_MISMATCH", semantic_hash)
            index = copy.deepcopy(dict(pack.get("knowledge_index", {})))
            covered = int(manifest["latest_sequence"])
            digest = semantic_hash.split(":", 1)[1][:16]
            checkpoint_id = f"checkpoint-{covered:020d}-{digest}"
            relative = f"checkpoints/{checkpoint_id}.json"
            payload = {
                "kind": CHECKPOINT_KIND, "format_version": FORMAT_VERSION, "checkpoint_id": checkpoint_id,
                "pack_id": manifest["pack_id"], "covered_sequence": covered,
                "authority_root_hash": manifest["authority_root_hash"], "logical_state_hash": semantic_hash,
                "schema_version": manifest["schema_version"], "created_at": _utc_now(),
                "authority": authority, "knowledge_index": index, "index_hash": _value_hash(index),
            }
            raw = _document_bytes(payload)
            if len(raw) > self.policy.max_checkpoint_bytes:
                raise KnowledgePersistenceError("CHECKPOINT_TOO_LARGE", str(len(raw)))
            path = self.root / relative
            checkpoint_bytes = _atomic_write(
                path, raw, before="C7_BEFORE_CHECKPOINT_WRITE", during="C7_DURING_CHECKPOINT_WRITE",
                before_replace="C7_BEFORE_CHECKPOINT_REPLACE", after_replace="C7_AFTER_CHECKPOINT_REPLACE", injector=injector,
            )
            descriptor = {
                "checkpoint_id": checkpoint_id, "path": relative, "covered_sequence": covered,
                "authority_root_hash": manifest["authority_root_hash"], "logical_state_hash": semantic_hash,
                "index_hash": payload["index_hash"], "file_hash": _sha256(raw), "file_bytes": len(raw),
            }
            check_manifest = {**manifest, "current_checkpoint": descriptor, "checkpoint_covered_sequence": covered}
            # Validate the exact persisted document before it is made discoverable.
            self._read_checkpoint(_finalize_manifest(check_manifest))
            updated = dict(manifest)
            updated.update({"generation": int(manifest["generation"]) + 1, "current_checkpoint": descriptor,
                            "checkpoint_covered_sequence": covered, "updated_at": _utc_now()})
            manifest_bytes = self._write_manifest(updated, injector)
        return {
            "kind": "KnowledgeCheckpointResult", "status": "PASS", "path": str(path),
            "covered_sequence": covered, "authority_root_hash": manifest["authority_root_hash"],
            "logical_state_hash": semantic_hash, "checkpoint_bytes_written": checkpoint_bytes,
            "manifest_bytes_written": manifest_bytes, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    def compact(
        self, *, max_segments: int | None = None, injector: FailureInjector | None = None,
        validate_full_replay: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        batch = min(max_segments or self.policy.compaction_batch_size, self.policy.compaction_batch_size)
        if batch < 2:
            raise KnowledgePersistenceError("INVALID_COMPACTION_BATCH", str(batch))
        with _WriteLock(self.root):
            manifest = self._manifest()
            descriptors = list(manifest["authoritative_segments"])
            if len(descriptors) < 2:
                return {"kind": "KnowledgeCompactionResult", "status": "NOT_DUE", "segments_before": len(descriptors), "segments_after": len(descriptors)}
            # The initial import/snapshot segment can be large. Keep it
            # immutable and compact bounded runs of small mutation segments so
            # maintenance does not repeatedly rewrite the corpus.
            start_index = 1 if len(descriptors) > 2 else 0
            end_index = min(start_index + batch, len(descriptors))
            checkpoint_sequence = int(manifest.get("checkpoint_covered_sequence", 0))
            if checkpoint_sequence:
                checkpoint_index = next((index + 1 for index, row in enumerate(descriptors) if int(row["sequence_end"]) == checkpoint_sequence), None)
                if checkpoint_index is not None and start_index < checkpoint_index < end_index:
                    end_index = checkpoint_index
                if end_index - start_index < 2 and checkpoint_index is not None:
                    start_index = checkpoint_index
                    end_index = min(start_index + batch, len(descriptors))
            candidates = descriptors[start_index:end_index]
            if len(candidates) < 2:
                return {"kind": "KnowledgeCompactionResult", "status": "NOT_DUE", "segments_before": len(descriptors), "segments_after": len(descriptors)}
            before_hash = None
            if validate_full_replay:
                before_hash = project_knowledge_semantic_hash(self.load(use_checkpoint=False))
            records: list[dict[str, Any]] = []
            for descriptor in candidates:
                records.extend(self._read_segment(descriptor, str(manifest["pack_id"]))["records"])
            compacted, relative = _build_segment(str(manifest["pack_id"]), records, str(candidates[0]["previous_authority_root_hash"]))
            new_descriptor, compacted_bytes = self._write_segment(compacted, relative, injector, compaction=True)
            replacement = [*descriptors[:start_index], new_descriptor, *descriptors[end_index:]]
            candidate_manifest = _finalize_manifest({**manifest, "authoritative_segments": replacement})
            _validate_manifest(candidate_manifest)
            original_record_hashes = [str(row["record_hash"]) for row in records]
            compacted_record_hashes = [str(row["record_hash"]) for row in compacted["records"]]
            if original_record_hashes != compacted_record_hashes or compacted["authority_root_hash"] != candidates[-1]["authority_root_hash"]:
                raise KnowledgePersistenceError("COMPACTION_RECORD_EQUIVALENCE_MISMATCH", relative)
            updated = dict(manifest)
            updated.update({"generation": int(manifest["generation"]) + 1, "authoritative_segments": replacement, "updated_at": _utc_now()})
            manifest_bytes = self._write_manifest(updated, injector)
            committed = self._manifest()
            self._read_segment(new_descriptor, str(committed["pack_id"]))
            after_hash = None
            if validate_full_replay:
                after_hash = project_knowledge_semantic_hash(self.load(use_checkpoint=False))
                if after_hash != before_hash:
                    raise KnowledgePersistenceError("COMPACTION_RELOAD_MISMATCH", relative)
            deleted = 0
            for descriptor in candidates:
                old = self.root / str(descriptor["path"])
                if old.exists() and old != self.root / relative:
                    old.unlink()
                    deleted += 1
            _fsync_directory(self.root / "segments")
        return {
            "kind": "KnowledgeCompactionResult", "status": "PASS",
            "segments_before": len(descriptors), "segments_after": len(replacement),
            "records_preserved": len(records), "old_segments_deleted": deleted,
            "record_sequence_equivalence": "PASS", "authority_root_equivalence": "PASS",
            "semantic_hash_before": before_hash, "semantic_hash_after": after_hash,
            "compaction_bytes_written": compacted_bytes, "manifest_bytes_written": manifest_bytes,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    def verify(self) -> dict[str, Any]:
        started = time.perf_counter()
        manifest = self._manifest()
        pack = self.load(use_checkpoint=False)
        referenced = {str(row["path"]).replace("/", os.sep) for row in manifest["authoritative_segments"]}
        actual = {
            str(path.relative_to(self.root)) for path in (self.root / "segments").glob("*.json") if path.is_file()
        } if (self.root / "segments").exists() else set()
        referenced_native = {str(pathlib.Path(value)) for value in referenced}
        orphans = sorted(actual - referenced_native)
        partial_temporaries = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*.tmp") if path.is_file())
        checkpoint_status = "MISSING_REBUILDABLE"
        if manifest.get("current_checkpoint"):
            try:
                self._read_checkpoint(manifest)
                checkpoint_status = "VALID"
            except KnowledgePersistenceError as exc:
                checkpoint_status = f"REJECTED_REBUILDABLE:{exc.code}"
        return {
            "kind": "KnowledgeStoreVerification", "status": "PASS",
            "format_version": FORMAT_VERSION, "pack_id": manifest["pack_id"],
            "latest_sequence": manifest["latest_sequence"], "authority_root_hash": manifest["authority_root_hash"],
            "semantic_hash": project_knowledge_semantic_hash(pack), "segment_count": len(manifest["authoritative_segments"]),
            "orphan_segments": orphans, "partial_temporaries": partial_temporaries,
            "checkpoint_status": checkpoint_status, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def detect_persistence_format(path: str | pathlib.Path) -> str:
    target = pathlib.Path(path)
    if target.is_file():
        return "1"
    if target.is_dir() and (target / "manifest.json").is_file():
        return "2"
    if target.exists():
        raise KnowledgePersistenceError("UNKNOWN_PERSISTENCE_LAYOUT", str(target))
    return "NEW"


def migrate_legacy_pack(
    source: str | pathlib.Path, target: str | pathlib.Path, *, policy: PersistencePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    from .store import load_legacy_project_knowledge

    source_path, target_path = pathlib.Path(source), pathlib.Path(target)
    if detect_persistence_format(source_path) != "1":
        raise KnowledgePersistenceError("MIGRATION_SOURCE_NOT_LEGACY", str(source_path))
    if target_path.exists():
        raise KnowledgePersistenceError("MIGRATION_TARGET_EXISTS", str(target_path))
    legacy = load_legacy_project_knowledge(source_path)
    before_hash = project_knowledge_semantic_hash(legacy)
    temporary = target_path.with_name(f".{target_path.name}.migration-{uuid.uuid4().hex}.tmp")
    started = time.perf_counter()
    try:
        store = SegmentedKnowledgeStore(temporary, policy=policy)
        store.initialize(legacy)
        store.create_checkpoint()
        migrated = store.load()
        after_hash = project_knowledge_semantic_hash(migrated)
        if before_hash != after_hash:
            raise KnowledgePersistenceError("MIGRATION_SEMANTIC_MISMATCH", f"{before_hash}!={after_hash}")
        os.replace(temporary, target_path)
        _fsync_directory(target_path.parent)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return {
        "kind": "ProjectKnowledgeMigrationReceipt", "status": "PASS", "source_format": "1", "target_format": FORMAT_VERSION,
        "source": str(source_path), "target": str(target_path), "legacy_retained": source_path.exists(),
        "dual_write": False, "semantic_hash_before": before_hash, "semantic_hash_after": after_hash,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def rollback_legacy_migration(source: str | pathlib.Path, target: str | pathlib.Path) -> dict[str, Any]:
    from .store import load_legacy_project_knowledge

    source_path, target_path = pathlib.Path(source), pathlib.Path(target)
    legacy = load_legacy_project_knowledge(source_path)
    store = SegmentedKnowledgeStore(target_path)
    migrated = store.load()
    source_hash, target_hash = project_knowledge_semantic_hash(legacy), project_knowledge_semantic_hash(migrated)
    if source_hash != target_hash:
        raise KnowledgePersistenceError("MIGRATION_ROLLBACK_HASH_MISMATCH", f"{source_hash}!={target_hash}")
    resolved = target_path.resolve()
    if target_path.parent.resolve() not in resolved.parents:
        raise KnowledgePersistenceError("UNSAFE_MIGRATION_ROLLBACK_TARGET", str(target_path))
    shutil.rmtree(target_path)
    return {"kind": "ProjectKnowledgeMigrationRollback", "status": "PASS", "legacy_active": True,
            "removed_v2_target": str(target_path), "semantic_hash": source_hash}
