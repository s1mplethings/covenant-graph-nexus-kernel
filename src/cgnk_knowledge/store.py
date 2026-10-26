from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from .persistence import (
    DEFAULT_POLICY,
    PersistencePolicy,
    SegmentedKnowledgeStore,
    TrackedKnowledgePack,
    attach_pending_mutation,
    build_pack_mutation,
    clone_pack,
    detect_persistence_format,
    _load_legacy_pack_document,
    tracked_pack,
)
from .projection import (
    ACTIVE_BUCKETS,
    IMPORTANCE_RANK,
    NEED_RANK,
    _build_knowledge_index,
    _knowledge_index_is_current,
    _rebuild_pack_buckets,
    _rebuild_pack_indexes,
)


def build_knowledge_index(pack: dict[str, Any]) -> dict[str, Any]:
    return _build_knowledge_index(pack)


def knowledge_index_is_current(pack: dict[str, Any]) -> bool:
    return _knowledge_index_is_current(pack)


def rebuild_pack_buckets(pack: dict[str, Any], *, sort_all_items: bool = True, copy_items: bool = True) -> dict[str, Any]:
    return _rebuild_pack_buckets(pack, sort_all_items=sort_all_items, copy_items=copy_items)


def rebuild_pack_indexes(pack: dict[str, Any], *, copy_items: bool = True) -> dict[str, Any]:
    return _rebuild_pack_indexes(pack, copy_items=copy_items)


def new_project_knowledge_pack(project: str, pack_id: str | None = None) -> dict[str, Any]:
    pack = {
        "kind": "ProjectKnowledgePack",
        "id": pack_id or f"pkp_{str(project or 'project').lower().replace(' ', '_')}",
        "project": project,
        "version": "1",
        "active_goals": [],
        "active_constraints": [],
        "active_decisions": [],
        "current_requirements": [],
        "module_mappings": [],
        "agent_mappings": [],
        "risks": [],
        "open_questions": [],
        "next_steps": [],
        "artifact_refs": [],
        "research_findings": [],
        "test_results": [],
        "archived_items": [],
        "discarded_items": [],
        "all_items": [],
        "diagnostics": [],
        "knowledge_revision": 0,
        "knowledge_index": {},
    }
    return tracked_pack(rebuild_pack_indexes(pack))


def load_legacy_project_knowledge(path: str | pathlib.Path) -> TrackedKnowledgePack:
    return _load_legacy_pack_document(path)


def load_project_knowledge(
    path: str | pathlib.Path, *, use_checkpoint: bool = True, as_of_sequence: int | None = None,
) -> dict[str, Any]:
    persistence_format = detect_persistence_format(path)
    if persistence_format == "1":
        if as_of_sequence is not None:
            raise ValueError("legacy ProjectKnowledgePack does not support as_of_sequence")
        return load_legacy_project_knowledge(path)
    if persistence_format == "2":
        return SegmentedKnowledgeStore(path).load(use_checkpoint=use_checkpoint, as_of_sequence=as_of_sequence)
    raise FileNotFoundError(path)


def save_legacy_project_knowledge(path: str | pathlib.Path, pack: dict[str, Any]) -> dict[str, Any]:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = rebuild_pack_indexes(dict(pack))
    data = (json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return {"kind": "KnowledgeStoreWriteResult", "path": str(target), "pack": clean, "diagnostics": []}


def _fallback_mutation(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any] | None:
    current_by_id = {str(row.get("id")): row for row in current.get("all_items", ())}
    desired_by_id = {str(row.get("id")): row for row in desired.get("all_items", ())}
    removed = sorted(set(current_by_id) - set(desired_by_id))
    if removed:
        raise ValueError("v2 persistence forbids deleting authoritative history; use lifecycle state: " + ",".join(removed))
    changed = sorted(
        item_id for item_id, item in desired_by_id.items()
        if item_id not in current_by_id
        or json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        != json.dumps(current_by_id[item_id], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    metadata_keys = ("kind", "id", "project", "version", "knowledge_revision", "diagnostics")
    metadata_changed = any(current.get(key) != desired.get(key) for key in metadata_keys)
    if not changed and not metadata_changed:
        return None
    return build_pack_mutation(desired, changed, operation_kind="UPSERT_ITEMS", provenance={"reason": "fallback_diff"})


def save_project_knowledge(
    path: str | pathlib.Path, pack: dict[str, Any], *, format_version: str | None = None,
    mutation: dict[str, Any] | list[dict[str, Any]] | None = None,
    policy: PersistencePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    target = pathlib.Path(path)
    detected = detect_persistence_format(target)
    requested = str(format_version) if format_version is not None else None
    if requested not in {None, "1", "2", "2.0"}:
        raise ValueError(f"unsupported persistence format: {requested}")
    if detected == "1":
        if requested in {"2", "2.0"}:
            raise ValueError("legacy stores require explicit migrate_legacy_pack")
        return save_legacy_project_knowledge(target, pack)
    if requested == "1":
        if detected == "2":
            raise ValueError("cannot write legacy format over a v2 store")
        return save_legacy_project_knowledge(target, pack)
    if detected == "NEW":
        # The production scale and cold-start gates qualify v2 as the default
        # only for newly created packs. Explicit v1 remains available above;
        # existing v1 packs keep their detected format and never auto-migrate.
        store = SegmentedKnowledgeStore(target, policy=policy)
        result = store.initialize(pack)
        if isinstance(pack, TrackedKnowledgePack):
            pack._persistence_root = str(target.resolve())
            pack._persistence_sequence = int(result["sequence_end"])
            pack._persistence_authority_root = str(result["authority_root_hash"])
            pack._pending_mutations.clear()
        return {**result, "pack": pack}
    store = SegmentedKnowledgeStore(target, policy=policy)
    mutations: list[dict[str, Any]]
    if isinstance(mutation, list):
        mutations = [dict(row) for row in mutation]
    elif isinstance(mutation, dict):
        mutations = [dict(mutation)]
    elif isinstance(pack, TrackedKnowledgePack) and pack._persistence_root == str(target.resolve()):
        mutations = [dict(row) for row in pack._pending_mutations]
    else:
        current = store.load()
        fallback = _fallback_mutation(current, pack)
        mutations = [fallback] if fallback else []
    expected_sequence = None
    expected_root = None
    if isinstance(pack, TrackedKnowledgePack) and pack._persistence_root == str(target.resolve()):
        expected_sequence = pack._persistence_sequence
        expected_root = pack._persistence_authority_root
    result = store.commit_mutations(mutations, expected_sequence=expected_sequence, expected_authority_root=expected_root)
    if isinstance(pack, TrackedKnowledgePack) and not result.get("no_op"):
        pack._persistence_sequence = int(result["sequence_end"])
        pack._persistence_authority_root = str(result["authority_root_hash"])
        pack._pending_mutations.clear()
    return {**result, "pack": pack}


def upsert_knowledge_items(pack: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    out = clone_pack(pack) if pack else new_project_knowledge_pack("CGKN")
    by_id = {str(row.get("id")): dict(row) for row in out.get("all_items", [])}
    diagnostics: list[dict[str, Any]] = []
    for item in items:
        by_id[str(item.get("id"))] = dict(item)
    for item in items:
        for superseded_id in item.get("supersedes", []):
            if superseded_id in by_id:
                by_id[superseded_id]["status"] = "superseded"
                by_id[superseded_id]["review_state"] = "rejected"
                by_id[superseded_id]["need_state"] = "not_needed"
                by_id[superseded_id]["retention"] = "archive"
                by_id[superseded_id]["superseded_by"] = item.get("id")
                diagnostics.append({"code": "CGNK_KNOWLEDGE_SUPERSEDED", "severity": "info", "message": f"{superseded_id} superseded"})
    out["all_items"] = list(by_id.values())
    out["diagnostics"] = list(out.get("diagnostics", [])) + diagnostics
    out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
    rebuild_pack_indexes(out)
    attach_pending_mutation(out, build_pack_mutation(out, [str(row.get("id")) for row in items], operation_kind="UPSERT_ITEMS"))
    return out


def archive_knowledge_item(pack: dict[str, Any], item_id: str, reason: str | None = None) -> dict[str, Any]:
    out = clone_pack(pack)
    out["all_items"] = [dict(item) for item in out.get("all_items", ())]
    changed = False
    for item in out.get("all_items", []):
        if item.get("id") == item_id:
            item["status"] = "archived"
            item["retention"] = "archive"
            item.setdefault("diagnostics", []).append({"code": "CGNK_KNOWLEDGE_SUPERSEDED", "severity": "info", "message": reason or "archived"})
            out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
            changed = True
    rebuild_pack_indexes(out)
    if changed:
        attach_pending_mutation(out, build_pack_mutation(out, [item_id], operation_kind="ARCHIVE", provenance={"reason": reason or "archived"}))
    return out


def discard_knowledge_item(pack: dict[str, Any], item_id: str, reason: str | None = None) -> dict[str, Any]:
    out = clone_pack(pack)
    out["all_items"] = [dict(item) for item in out.get("all_items", ())]
    changed = False
    for item in out.get("all_items", []):
        if item.get("id") == item_id:
            item["retention"] = "discard"
            item.setdefault("diagnostics", []).append({"code": "CGNK_KNOWLEDGE_DISCARDED", "severity": "info", "message": reason or "discarded"})
            out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
            changed = True
    rebuild_pack_indexes(out)
    if changed:
        attach_pending_mutation(out, build_pack_mutation(out, [item_id], operation_kind="DISCARD", provenance={"reason": reason or "discarded"}))
    return out
