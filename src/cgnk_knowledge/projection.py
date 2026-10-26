"""Pure ProjectKnowledgePack index and compatibility-bucket projection.

This module owns deterministic in-memory projections of authoritative
knowledge items. It has no persistence, migration, recovery, provider, or
application dependency, so domain mutation and persistence replay share the
same projection semantics without calling each other.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping


IMPORTANCE_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "noise": 4}
NEED_RANK = {"needed_now": 0, "needed_later": 1, "reference_only": 2, "unknown": 3, "not_needed": 4}
ACTIVE_BUCKETS = {
    "goal": "active_goals",
    "constraint": "active_constraints",
    "decision": "active_decisions",
    "requirement": "current_requirements",
    "module_mapping": "module_mappings",
    "agent_mapping": "agent_mappings",
    "risk": "risks",
    "open_question": "open_questions",
    "next_step": "next_steps",
    "artifact_ref": "artifact_refs",
    "research_finding": "research_findings",
    "test_result": "test_results",
}
_TOKEN = re.compile(r"[A-Za-z0-9_.+-]+|[\u3400-\u9fff]+")


def _index_terms(item: Mapping[str, Any]) -> set[str]:
    value = " ".join((
        str(item.get("id", "")), str(item.get("title", "")), str(item.get("content", "")),
        " ".join(str(row) for row in item.get("tags", ())), str(item.get("subject_ref", "")),
        str(item.get("branch_ref", "")),
    ))
    return {token.casefold() for token in _TOKEN.findall(value) if len(token) > 1}


def _content_hash(item: Mapping[str, Any]) -> str:
    existing = str(item.get("content_hash", ""))
    return existing or "sha256:" + hashlib.sha256(str(item.get("content", "")).encode("utf-8")).hexdigest()


def _derived(item: Mapping[str, Any]) -> bool:
    return (
        item.get("evidence_kind") == "derived"
        or item.get("retention") == "compress"
        or bool({str(tag).casefold() for tag in item.get("tags", ())} & {"summary", "lossy-summary", "abstraction"})
    )


def _active(item: Mapping[str, Any]) -> bool:
    return (
        item.get("status", "active") == "active"
        and item.get("retention") != "discard"
        and item.get("review_state") != "rejected"
        and item.get("importance") != "noise"
        and item.get("derived_state", "fresh") != "stale"
    )


def _sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        IMPORTANCE_RANK.get(item.get("importance"), 9), NEED_RANK.get(item.get("need_state"), 9),
        str(item.get("type", "")), str(item.get("id", "")),
    )


def _sorted_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=_sort_key)


def _build_knowledge_index(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Build the one deterministic index belonging to ProjectKnowledgePack."""
    by_content_hash: dict[str, list[str]] = {}
    by_subject_ref: dict[str, list[str]] = {}
    by_branch_ref: dict[str, list[str]] = {}
    by_term: dict[str, list[str]] = {}
    dependents: dict[str, list[str]] = {}
    by_id: dict[str, int] = {}
    derived_ids: list[str] = []
    bucket_positions = {
        bucket: {str(item.get("id")): position for position, item in enumerate(pack.get(bucket, ())) if item.get("id")}
        for bucket in (*ACTIVE_BUCKETS.values(), "archived_items", "discarded_items")
    }
    for position, item in enumerate(pack.get("all_items", [])):
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        by_id[item_id] = position
        content_hash = _content_hash(item)
        if content_hash:
            by_content_hash.setdefault(content_hash, []).append(item_id)
        subject_ref = str(item.get("subject_ref", ""))
        if subject_ref:
            by_subject_ref.setdefault(subject_ref, []).append(item_id)
        branch_ref = str(item.get("branch_ref", item.get("scope", "")))
        if branch_ref:
            by_branch_ref.setdefault(branch_ref, []).append(item_id)
        for term in _index_terms(item):
            by_term.setdefault(term, []).append(item_id)
        if _derived(item):
            derived_ids.append(item_id)
            for dependency_id in item.get("source_refs", ()):
                dependents.setdefault(str(dependency_id), []).append(item_id)
    return {
        "kind": "KnowledgeIndex", "schema_version": "1.0",
        "pack_revision": int(pack.get("knowledge_revision", 0)),
        "item_count": len(pack.get("all_items", [])), "by_id": by_id,
        "by_content_hash": {key: sorted(set(value)) for key, value in sorted(by_content_hash.items())},
        "by_subject_ref": {key: sorted(set(value)) for key, value in sorted(by_subject_ref.items())},
        "by_branch_ref": {key: sorted(set(value)) for key, value in sorted(by_branch_ref.items())},
        "by_term": {key: sorted(set(value)) for key, value in sorted(by_term.items())},
        "dependents": {key: sorted(set(value)) for key, value in sorted(dependents.items())},
        "derived_ids": sorted(set(derived_ids)), "bucket_positions": bucket_positions,
    }


def _knowledge_index_is_current(pack: Mapping[str, Any]) -> bool:
    index = pack.get("knowledge_index")
    return bool(
        isinstance(index, dict) and index.get("kind") == "KnowledgeIndex"
        and index.get("schema_version") == "1.0"
        and int(index.get("pack_revision", -1)) == int(pack.get("knowledge_revision", 0))
        and int(index.get("item_count", -1)) == len(pack.get("all_items", []))
    )


def _rebuild_pack_buckets(pack: dict[str, Any], *, sort_all_items: bool = True, copy_items: bool = True) -> dict[str, Any]:
    all_items = [dict(row) for row in pack.get("all_items", [])] if copy_items else list(pack.get("all_items", []))
    if sort_all_items:
        all_items = _sorted_items(all_items)
    pack["all_items"] = all_items
    for bucket in ACTIVE_BUCKETS.values():
        pack[bucket] = []
    for item in all_items:
        if _active(item):
            bucket = ACTIVE_BUCKETS.get(item.get("type"))
            if bucket:
                pack[bucket].append(item)
    pack["archived_items"] = _sorted_items(list({
        row["id"]: row for row in pack.get("archived_items", [])
        + [row for row in all_items if row.get("status") == "archived" or row.get("retention") == "archive"]
    }.values()))
    pack["discarded_items"] = _sorted_items(list({
        row["id"]: row for row in pack.get("discarded_items", [])
        + [row for row in all_items if row.get("retention") == "discard"]
    }.values()))
    pack.setdefault("knowledge_revision", 0)
    return pack


def _rebuild_pack_indexes(pack: dict[str, Any], *, copy_items: bool = True) -> dict[str, Any]:
    _rebuild_pack_buckets(pack, copy_items=copy_items)
    pack["knowledge_index"] = _build_knowledge_index(pack)
    return pack


def _append_index_entry(index: dict[str, Any], item: Mapping[str, Any], position: int) -> None:
    item_id = str(item["id"])
    index.setdefault("by_id", {})[item_id] = position
    for field, mapping_name in (("content_hash", "by_content_hash"), ("subject_ref", "by_subject_ref"), ("branch_ref", "by_branch_ref")):
        value = str(item.get(field, ""))
        if value:
            values = index.setdefault(mapping_name, {}).setdefault(value, [])
            if item_id not in values:
                values.append(item_id); values.sort()
    for term in _index_terms(item):
        values = index.setdefault("by_term", {}).setdefault(term, [])
        if item_id not in values:
            values.append(item_id); values.sort()
    if _derived(item):
        if item_id not in index.setdefault("derived_ids", []):
            index["derived_ids"].append(item_id); index["derived_ids"].sort()
        for dependency_id in item.get("source_refs", ()):
            values = index.setdefault("dependents", {}).setdefault(str(dependency_id), [])
            if item_id not in values:
                values.append(item_id); values.sort()


def _replace_index_content(index: dict[str, Any], old: Mapping[str, Any], new: Mapping[str, Any]) -> None:
    item_id = str(new["id"])
    old_hash, new_hash = str(old.get("content_hash", "")), str(new.get("content_hash", ""))
    if old_hash != new_hash:
        old_values = index.get("by_content_hash", {}).get(old_hash, [])
        index.get("by_content_hash", {})[old_hash] = [value for value in old_values if value != item_id]
        index.setdefault("by_content_hash", {}).setdefault(new_hash, []).append(item_id)
    index["by_term"] = _build_knowledge_index({"all_items": [new], "knowledge_revision": 0})["by_term"] | {
        key: [value for value in values if value != item_id]
        for key, values in index.get("by_term", {}).items() if any(value != item_id for value in values)
    }
    _append_index_entry(index, new, int(index["by_id"][item_id]))


def _sync_pack_buckets(pack: dict[str, Any], index: dict[str, Any], changed: Mapping[str, Mapping[str, Any]]) -> int:
    """Update compatibility buckets by indexed position, touching changed nodes only."""
    bucket_names = (*ACTIVE_BUCKETS.values(), "archived_items", "discarded_items")
    positions = index.setdefault("bucket_positions", {})
    for bucket in bucket_names:
        positions.setdefault(bucket, {
            str(item.get("id")): position for position, item in enumerate(pack.get(bucket, ())) if item.get("id")
        })

    def desired(item: Mapping[str, Any]) -> set[str]:
        values: set[str] = set()
        active_bucket = ACTIVE_BUCKETS.get(item.get("type"))
        if active_bucket and _active(item):
            values.add(active_bucket)
        if item.get("status") in {"archived", "superseded", "retracted"} or item.get("retention") == "archive":
            values.add("archived_items")
        if item.get("retention") == "discard":
            values.add("discarded_items")
        return values

    operations = 0
    for item_id, item in changed.items():
        desired_buckets = desired(item)
        current_buckets = {bucket for bucket in bucket_names if item_id in positions[bucket]}
        for bucket in current_buckets - desired_buckets:
            rows = pack.setdefault(bucket, [])
            position = int(positions[bucket].pop(item_id)); last = rows.pop()
            if position < len(rows):
                rows[position] = last; positions[bucket][str(last["id"])] = position
            operations += 1
        for bucket in current_buckets & desired_buckets:
            pack[bucket][int(positions[bucket][item_id])] = dict(item); operations += 1
        for bucket in desired_buckets - current_buckets:
            rows = pack.setdefault(bucket, []); positions[bucket][item_id] = len(rows)
            rows.append(dict(item)); operations += 1
    return operations
