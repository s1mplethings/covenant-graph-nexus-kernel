from __future__ import annotations

import hashlib
import re
import time
from enum import Enum
from typing import Any, Callable, Mapping

from .normalize import normalize_text, stable_hash_for
from .persistence import attach_pending_mutation, build_pack_mutation
from .projection import (
    ACTIVE_BUCKETS,
    _append_index_entry as _append_index,
    _build_knowledge_index as build_knowledge_index,
    _knowledge_index_is_current as knowledge_index_is_current,
    _replace_index_content,
    _sync_pack_buckets as _sync_buckets,
)


class KnowledgeRelation(str, Enum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    SUPPORTING = "SUPPORTING"
    NOVEL = "NOVEL"
    SUPERSEDING = "SUPERSEDING"
    CONTRADICTING = "CONTRADICTING"
    CORRECTION = "CORRECTION"
    RETRACTION = "RETRACTION"
    UNRESOLVED_RELATION = "UNRESOLVED_RELATION"


class KnowledgeMaintenancePolicy(str, Enum):
    FLAT_APPEND = "FLAT_APPEND"
    EAGER_GLOBAL_REBUILD = "EAGER_GLOBAL_REBUILD"
    LOCAL_LAZY = "LOCAL_LAZY"


RelationClassifier = Callable[[Mapping[str, Any], tuple[Mapping[str, Any], ...]], Mapping[str, Any]]
AbstractionReducer = Callable[[Mapping[str, Any], tuple[Mapping[str, Any], ...]], str]

_ITEM_TYPES = {
    "goal", "constraint", "decision", "preference", "requirement", "risk", "open_question",
    "artifact_ref", "module_mapping", "agent_mapping", "next_step", "research_finding",
    "test_result", "correction",
}
_SCOPES = {"session", "project", "global", "project.cgkn", "project.cgnk", "agent", "module"}
_IMPORTANCE = {"critical", "high", "medium", "low", "noise"}
_NEED_STATES = {"needed_now", "needed_later", "reference_only", "not_needed", "unknown"}
_EXPLICIT_RELATIONS = set(KnowledgeRelation) - {KnowledgeRelation.EXACT_DUPLICATE}
_RELATION_EDGE = {
    KnowledgeRelation.SUPPORTING: ("SUPPORTS", "SUPPORTED_BY"),
    KnowledgeRelation.SUPERSEDING: ("SUPERSEDES", "SUPERSEDED_BY"),
    KnowledgeRelation.CONTRADICTING: ("CONTRADICTS", "CONTRADICTED_BY"),
    KnowledgeRelation.CORRECTION: ("CORRECTS", "CORRECTED_BY"),
    KnowledgeRelation.RETRACTION: ("RETRACTS", "RETRACTED_BY"),
    KnowledgeRelation.UNRESOLVED_RELATION: ("MAY_RELATE_TO", "MAY_RELATE_TO"),
}


def raw_content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _item_id(content_hash: str, source_ref: str, source_version: str) -> str:
    seed = f"{content_hash}|{source_ref}|{source_version}".encode("utf-8")
    return "ke_" + hashlib.sha256(seed).hexdigest()[:16]


def _title(content: str) -> str:
    value = re.sub(r"\s+", " ", content).strip()
    return value[:77] + "..." if len(value) > 80 else value


def _version_key(value: str) -> tuple[tuple[int, Any], ...]:
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.findall(r"\d+|[^\d]+", value))


def _derived(item: Mapping[str, Any]) -> bool:
    tags = {str(tag).casefold() for tag in item.get("tags", ())}
    return item.get("evidence_kind") == "derived" or item.get("retention") == "compress" or bool(
        tags & {"summary", "lossy-summary", "abstraction"}
    )


def _active(item: Mapping[str, Any]) -> bool:
    return (
        item.get("status", "active") == "active"
        and item.get("retention") != "discard"
        and item.get("review_state") != "rejected"
        and item.get("importance") != "noise"
        and item.get("derived_state", "fresh") != "stale"
    )


def _ensure_index(pack: dict[str, Any]) -> tuple[dict[str, Any], int]:
    pack.setdefault("knowledge_revision", 0)
    if knowledge_index_is_current(pack):
        return pack["knowledge_index"], 0
    pack["knowledge_index"] = build_knowledge_index(pack)
    return pack["knowledge_index"], len(pack.get("all_items", ()))


def _relation_for(
    evidence: Mapping[str, Any], candidates: tuple[Mapping[str, Any], ...],
    classifier: RelationClassifier | None,
) -> tuple[KnowledgeRelation, str, int]:
    explicit = str(evidence.get("relation", "AUTO")).upper()
    target_id = str(evidence.get("target_id", ""))
    if explicit != "AUTO":
        relation = KnowledgeRelation(explicit)
        if relation not in _EXPLICIT_RELATIONS:
            raise ValueError("EXACT_DUPLICATE is determined by content identity")
        return relation, target_id, 0
    semantic_hash = stable_hash_for(str(evidence["content"]), str(evidence["item_type"]), str(evidence["scope"]))
    for candidate in reversed(candidates):
        if str(candidate.get("semantic_hash", candidate.get("stable_hash", ""))) == semantic_hash:
            return KnowledgeRelation.SUPPORTING, str(candidate["id"]), 0
    version = str(evidence.get("source_version", ""))
    versioned = [item for item in candidates if str(item.get("source_version", ""))]
    if version and versioned:
        target = max(versioned, key=lambda item: _version_key(str(item.get("source_version", ""))))
        if _version_key(version) > _version_key(str(target["source_version"])):
            return KnowledgeRelation.SUPERSEDING, str(target["id"]), 0
    if not candidates:
        return KnowledgeRelation.NOVEL, "", 0
    if classifier is None:
        return KnowledgeRelation.UNRESOLVED_RELATION, str(candidates[-1]["id"]), 0
    value = classifier(evidence, candidates)
    relation = KnowledgeRelation(str(value.get("relation", "UNRESOLVED_RELATION")))
    return relation, str(value.get("target_id", target_id)), 1


def _validate_target(
    relation: KnowledgeRelation, target_id: str, evidence: Mapping[str, Any], by_id: Mapping[str, int], all_items: list[dict[str, Any]],
) -> Mapping[str, Any] | None:
    if relation is KnowledgeRelation.NOVEL:
        if target_id:
            raise ValueError("NOVEL evidence cannot declare target_id")
        return None
    if not target_id or target_id not in by_id:
        raise ValueError(f"{relation.value} requires an existing target_id")
    target = all_items[int(by_id[target_id])]
    if str(target.get("scope", "")) != str(evidence["scope"]):
        raise ValueError("relation target scope differs from evidence scope")
    subject_ref = str(evidence.get("subject_ref", ""))
    if subject_ref and str(target.get("subject_ref", "")) not in {"", subject_ref}:
        raise ValueError("relation target subject differs from evidence subject")
    if relation is KnowledgeRelation.SUPERSEDING:
        new_version, old_version = str(evidence.get("source_version", "")), str(target.get("source_version", ""))
        if not new_version or not old_version or _version_key(new_version) <= _version_key(old_version):
            raise ValueError("SUPERSEDING requires a strictly newer source_version")
    return target


def _mark_relations(
    relation: KnowledgeRelation, new_item: dict[str, Any], target: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if target is None or relation is KnowledgeRelation.NOVEL:
        return None
    changed = dict(target)
    forward, reverse = _RELATION_EDGE[relation]
    new_item["relations"].append({"type": forward, "target_id": str(target["id"])})
    reverse_relations = [dict(value) for value in changed.get("relations", ())]
    reverse_relations.append({"type": reverse, "target_id": str(new_item["id"])})
    changed["relations"] = sorted(
        {f"{value['type']}|{value['target_id']}": value for value in reverse_relations}.values(),
        key=lambda value: (value["type"], value["target_id"]),
    )
    if relation in {KnowledgeRelation.SUPERSEDING, KnowledgeRelation.CORRECTION}:
        changed.update({
            "status": "superseded", "review_state": "rejected", "need_state": "not_needed",
            "retention": "archive", "superseded_by": new_item["id"],
        })
        new_item["supersedes"] = [str(target["id"])]
    elif relation is KnowledgeRelation.RETRACTION:
        changed.update({"status": "retracted", "review_state": "rejected", "need_state": "not_needed", "retention": "archive"})
        new_item["evidence_kind"] = "tombstone"
    elif relation is KnowledgeRelation.CONTRADICTING:
        changed["review_state"] = "conflict"
        new_item["review_state"] = "conflict"
    elif relation is KnowledgeRelation.UNRESOLVED_RELATION:
        new_item["review_state"] = "candidate"
    return changed


def _dependent_closure(index: Mapping[str, Any], seeds: set[str]) -> list[str]:
    queue = list(sorted(seeds))
    seen: set[str] = set()
    while queue:
        current = queue.pop(0)
        for dependent in index.get("dependents", {}).get(current, ()):
            if dependent not in seen:
                seen.add(dependent)
                queue.append(dependent)
    return sorted(seen)


def make_derived_abstraction(
    abstraction_id: str, content: str, source_refs: list[str], *, branch_ref: str,
    dependency_mode: str = "explicit", scope: str = "project", item_type: str = "research_finding",
) -> dict[str, Any]:
    if not abstraction_id or not content or not source_refs or dependency_mode not in {"explicit", "branch"}:
        raise ValueError("derived abstraction identity, content, sources, and dependency mode are required")
    content_hash = raw_content_hash(content)
    return {
        "kind": "KnowledgeItem", "id": abstraction_id, "title": _title(content), "type": item_type,
        "scope": scope, "content": content, "source_refs": list(source_refs),
        "tags": ["summary"], "importance": "high", "need_state": "needed_now",
        "retention": "compress", "review_state": "accepted", "status": "active",
        "supersedes": [], "stable_hash": content_hash, "content_hash": content_hash,
        "semantic_hash": stable_hash_for(content, item_type, scope), "evidence_kind": "derived",
        "subject_ref": "", "branch_ref": branch_ref, "source_version": "",
        "relations": [], "derived_state": "fresh", "stale_due_to": [], "revision": 1,
        "dependency_mode": dependency_mode, "refresh_count": 0, "diagnostics": [],
    }


def internalize_evidence(
    pack: dict[str, Any], evidence: Mapping[str, Any], *,
    policy: KnowledgeMaintenancePolicy | str = KnowledgeMaintenancePolicy.LOCAL_LAZY,
    classifier: RelationClassifier | None = None,
    eager_reducer: AbstractionReducer | None = None,
) -> dict[str, Any]:
    """Commit one raw observation into the existing ProjectKnowledgePack authority."""
    started = time.perf_counter()
    policy = KnowledgeMaintenancePolicy(policy)
    content = evidence.get("content")
    item_type = str(evidence.get("item_type", "research_finding"))
    scope = str(evidence.get("scope", "project"))
    source_ref = str(evidence.get("source_ref", ""))
    importance = str(evidence.get("importance", "medium"))
    need_state = str(evidence.get("need_state", "unknown"))
    if (
        not isinstance(content, str) or not content or item_type not in _ITEM_TYPES or scope not in _SCOPES
        or not source_ref or importance not in _IMPORTANCE or need_state not in _NEED_STATES
    ):
        raise ValueError("content, valid item_type/scope, and source_ref are required")
    out = pack
    index, index_scan = _ensure_index(out)
    all_items = list(out.get("all_items", ()))
    content_hash = raw_content_hash(content)
    requested_subject = str(evidence.get("subject_ref", ""))
    duplicate_ids = [
        item_id for item_id in index.get("by_content_hash", {}).get(content_hash, ())
        if item_id in index.get("by_id", {})
        and str(all_items[int(index["by_id"][item_id])].get("type", "")) == item_type
        and str(all_items[int(index["by_id"][item_id])].get("scope", "")) == scope
        and str(all_items[int(index["by_id"][item_id])].get("subject_ref", "")) == requested_subject
    ]
    lifecycle = ["OBSERVED", "IDENTIFIED"]
    if duplicate_ids:
        existing_id = duplicate_ids[0]
        position = int(index["by_id"][existing_id])
        existing = dict(all_items[position])
        source_refs = sorted(set(map(str, existing.get("source_refs", ()))) | {source_ref})
        changed = source_refs != list(existing.get("source_refs", ()))
        bucket_touched = 0
        if changed:
            existing["source_refs"] = source_refs
            existing["observation_count"] = int(existing.get("observation_count", 1)) + 1
            existing.setdefault("content_hash", content_hash)
            existing.setdefault("semantic_hash", stable_hash_for(content, item_type, scope))
            existing.setdefault("evidence_kind", "raw")
            all_items[position] = existing
            out["all_items"] = all_items
            out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
            index["pack_revision"] = out["knowledge_revision"]
            bucket_touched = _sync_buckets(out, index, {existing_id: existing})
        persistence_mutation = (
            build_pack_mutation(
                out, [existing_id], operation_kind="UPSERT_ITEMS",
                provenance={"relation": KnowledgeRelation.EXACT_DUPLICATE.value, "policy": policy.value},
            )
            if changed else None
        )
        attach_pending_mutation(out, persistence_mutation)
        lifecycle.extend(["DEDUPED", "AVAILABLE"])
        return {
            "kind": "KnowledgeInternalizationResult", "pack": out,
            "persistence_mutation": persistence_mutation,
            "receipt": {
                "kind": "KnowledgeInternalizationReceipt", "schema_version": "1.0",
                "relation": KnowledgeRelation.EXACT_DUPLICATE.value, "evidence_id": existing_id,
                "content_hash": content_hash, "raw_committed": False, "lifecycle": lifecycle,
                "observation_metadata_updated": changed,
                "model_calls": 0, "provider_calls": 0, "nodes_invalidated": [], "nodes_recomputed": [],
                "unrelated_nodes_touched": 0, "index_items_scanned": index_scan,
                "candidate_items_visited": 1, "bucket_items_touched": bucket_touched,
                "policy": policy.value, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        }

    subject_ref = requested_subject
    branch_ref = str(evidence.get("branch_ref", scope))
    candidate_ids = list(index.get("by_subject_ref", {}).get(subject_ref, ())) if subject_ref else []
    candidates = tuple(
        all_items[int(index["by_id"][item_id])]
        for item_id in candidate_ids
        if item_id in index.get("by_id", {})
        and not _derived(all_items[int(index["by_id"][item_id])])
        and all_items[int(index["by_id"][item_id])].get("status", "active") == "active"
        and all_items[int(index["by_id"][item_id])].get("review_state") != "rejected"
    )
    relation, target_id, model_calls = _relation_for(evidence, candidates, classifier)
    target = _validate_target(relation, target_id, evidence, index.get("by_id", {}), all_items)
    source_version = str(evidence.get("source_version", ""))
    evidence_id = _item_id(content_hash, source_ref, source_version)
    new_item = {
        "kind": "KnowledgeItem", "id": evidence_id, "title": _title(content), "type": item_type,
        "scope": scope, "content": content, "source_refs": [source_ref],
        "tags": sorted(set(map(str, evidence.get("tags", ()))) | {"raw-evidence"}),
        "importance": importance,
        "need_state": need_state, "retention": "keep",
        "review_state": "accepted", "status": "active", "supersedes": [],
        "stable_hash": content_hash, "content_hash": content_hash,
        "semantic_hash": stable_hash_for(content, item_type, scope), "evidence_kind": "raw",
        "subject_ref": subject_ref, "branch_ref": branch_ref, "source_version": source_version,
        "observed_at": str(evidence.get("observed_at", "")), "relations": [],
        "observation_count": 1, "revision": 1, "diagnostics": [],
    }
    changed_target = _mark_relations(relation, new_item, target)
    changed: dict[str, dict[str, Any]] = {}
    seeds: set[str] = set()
    if changed_target is not None:
        position = int(index["by_id"][str(changed_target["id"])])
        all_items[position] = changed_target
        changed[str(changed_target["id"])] = changed_target
        seeds.add(str(changed_target["id"]))
    position = len(all_items)
    all_items.append(new_item)
    changed[evidence_id] = new_item
    _append_index(index, new_item, position)
    lifecycle.extend(["LOCATED", "RAW_COMMITTED", "RELATION_CLASSIFIED"])

    if policy is KnowledgeMaintenancePolicy.FLAT_APPEND:
        invalidated: list[str] = []
    elif policy is KnowledgeMaintenancePolicy.EAGER_GLOBAL_REBUILD:
        invalidated = list(index.get("derived_ids", ()))
    else:
        branch_derived = {
            item_id for item_id in index.get("by_branch_ref", {}).get(branch_ref, ())
            if item_id in index.get("by_id", {})
            and _derived(all_items[int(index["by_id"][item_id])])
            and all_items[int(index["by_id"][item_id])].get("dependency_mode", "explicit") == "branch"
        }
        invalidated = sorted(set(_dependent_closure(index, seeds)) | branch_derived)
    for item_id in invalidated:
        item_position = int(index["by_id"][item_id])
        stale = dict(all_items[item_position])
        stale["derived_state"] = "stale"
        stale["stale_due_to"] = sorted(set(map(str, stale.get("stale_due_to", ()))) | seeds | {evidence_id})
        all_items[item_position] = stale
        changed[item_id] = stale
    lifecycle.extend(["DEPENDENTS_INVALIDATED", "DERIVED_STALE"])
    out["all_items"] = all_items
    out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
    index["pack_revision"] = out["knowledge_revision"]
    index["item_count"] = len(all_items)
    bucket_touched = _sync_buckets(out, index, changed)
    recomputed: list[str] = []
    if policy is KnowledgeMaintenancePolicy.EAGER_GLOBAL_REBUILD and invalidated:
        if eager_reducer is None:
            raise ValueError("EAGER_GLOBAL_REBUILD requires eager_reducer")
        refresh = refresh_stale_abstractions(out, node_ids=invalidated, reducer=eager_reducer)
        out = refresh["pack"]
        recomputed = list(refresh["receipt"]["nodes_recomputed"])
        refreshed_index = out.get("knowledge_index", {}).get("by_id", {})
        for item_id in recomputed:
            if item_id in refreshed_index:
                changed[item_id] = out["all_items"][int(refreshed_index[item_id])]
    persistence_mutation = build_pack_mutation(
        out, changed,
        operation_kind="UPSERT_ITEMS",
        provenance={"relation": relation.value, "policy": policy.value},
    )
    attach_pending_mutation(out, persistence_mutation)
    lifecycle.extend(["INTERNALIZED", "AVAILABLE"])
    return {
        "kind": "KnowledgeInternalizationResult", "pack": out,
        "persistence_mutation": persistence_mutation,
        "receipt": {
            "kind": "KnowledgeInternalizationReceipt", "schema_version": "1.0",
            "relation": relation.value, "evidence_id": evidence_id, "target_id": target_id,
            "content_hash": content_hash, "raw_committed": True, "lifecycle": lifecycle,
            "model_calls": model_calls, "provider_calls": model_calls,
            "nodes_invalidated": invalidated, "nodes_recomputed": recomputed,
            "unrelated_nodes_touched": 0, "index_items_scanned": index_scan,
            "candidate_items_visited": len(candidates), "bucket_items_touched": bucket_touched,
            "policy": policy.value, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    }


def refresh_stale_abstractions(
    pack: dict[str, Any], *, node_ids: list[str] | None = None,
    branch_ref: str = "", reducer: AbstractionReducer | None = None,
) -> dict[str, Any]:
    """Explicit cold/on-demand refresh. Invalidation never calls this implicitly."""
    started = time.perf_counter()
    out = pack
    index, index_scan = _ensure_index(out)
    all_items = list(out.get("all_items", ()))
    requested = set(node_ids or index.get("derived_ids", ()))
    if branch_ref:
        requested &= set(index.get("by_branch_ref", {}).get(branch_ref, ()))
    stale_ids = sorted(
        item_id for item_id in requested
        if item_id in index.get("by_id", {})
        and all_items[int(index["by_id"][item_id])].get("derived_state") == "stale"
    )
    if reducer is None:
        return {
            "kind": "KnowledgeRefreshResult", "pack": out,
            "receipt": {
                "kind": "KnowledgeRefreshReceipt", "schema_version": "1.0", "status": "PENDING_REDUCER",
                "requested_nodes": stale_ids, "nodes_recomputed": [], "model_calls": 0,
                "index_items_scanned": index_scan, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        }
    changed: dict[str, dict[str, Any]] = {}
    recomputed: list[str] = []
    pending = set(stale_ids)
    while pending:
        progressed = False
        for item_id in sorted(pending):
            position = int(index["by_id"][item_id])
            item = all_items[position]
            sources = tuple(
                all_items[int(index["by_id"][source_id])]
                for source_id in item.get("source_refs", ()) if source_id in index.get("by_id", {})
            )
            if any(source.get("derived_state") == "stale" for source in sources):
                continue
            content = reducer(item, sources)
            if not isinstance(content, str) or not content:
                raise ValueError(f"reducer returned empty abstraction for {item_id}")
            refreshed = dict(item)
            refreshed.update({
                "content": content, "title": _title(content), "content_hash": raw_content_hash(content),
                "stable_hash": raw_content_hash(content),
                "semantic_hash": stable_hash_for(content, str(item.get("type", "research_finding")), str(item.get("scope", "project"))),
                "derived_state": "fresh", "stale_due_to": [],
                "revision": int(item.get("revision", 1)) + 1,
                "refresh_count": int(item.get("refresh_count", 0)) + 1,
            })
            all_items[position] = refreshed
            _replace_index_content(index, item, refreshed)
            changed[item_id] = refreshed
            recomputed.append(item_id)
            pending.remove(item_id)
            progressed = True
        if not progressed:
            break
    out["all_items"] = all_items
    if recomputed:
        out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
        index["pack_revision"] = out["knowledge_revision"]
        _sync_buckets(out, index, changed)
    persistence_mutation = (
        build_pack_mutation(out, recomputed, operation_kind="REFRESH") if recomputed else None
    )
    attach_pending_mutation(out, persistence_mutation)
    return {
        "kind": "KnowledgeRefreshResult", "pack": out,
        "persistence_mutation": persistence_mutation,
        "receipt": {
            "kind": "KnowledgeRefreshReceipt", "schema_version": "1.0",
            "status": "PASS" if not pending else "PARTIAL_BLOCKED_DEPENDENCY",
            "requested_nodes": stale_ids, "nodes_recomputed": recomputed,
            "blocked_nodes": sorted(pending), "model_calls": 0,
            "index_items_scanned": index_scan, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    }
