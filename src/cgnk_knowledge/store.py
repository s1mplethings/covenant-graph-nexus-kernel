from __future__ import annotations

import json
import hashlib
import pathlib
import re
from typing import Any


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


def _index_terms(item: dict[str, Any]) -> set[str]:
    value = " ".join(
        (
            str(item.get("id", "")),
            str(item.get("title", "")),
            str(item.get("content", "")),
            " ".join(str(row) for row in item.get("tags", ())),
            str(item.get("subject_ref", "")),
            str(item.get("branch_ref", "")),
        )
    )
    return {token.casefold() for token in _TOKEN.findall(value) if len(token) > 1}


def _content_hash(item: dict[str, Any]) -> str:
    existing = str(item.get("content_hash", ""))
    return existing or "sha256:" + hashlib.sha256(str(item.get("content", "")).encode("utf-8")).hexdigest()


def build_knowledge_index(pack: dict[str, Any]) -> dict[str, Any]:
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
        derived = item.get("evidence_kind") == "derived" or item.get("retention") == "compress" or bool(
            {str(tag).casefold() for tag in item.get("tags", ())} & {"summary", "lossy-summary", "abstraction"}
        )
        if derived:
            derived_ids.append(item_id)
            for dependency_id in item.get("source_refs", ()):
                dependents.setdefault(str(dependency_id), []).append(item_id)
    return {
        "kind": "KnowledgeIndex",
        "schema_version": "1.0",
        "pack_revision": int(pack.get("knowledge_revision", 0)),
        "item_count": len(pack.get("all_items", [])),
        "by_id": by_id,
        "by_content_hash": {key: sorted(set(value)) for key, value in sorted(by_content_hash.items())},
        "by_subject_ref": {key: sorted(set(value)) for key, value in sorted(by_subject_ref.items())},
        "by_branch_ref": {key: sorted(set(value)) for key, value in sorted(by_branch_ref.items())},
        "by_term": {key: sorted(set(value)) for key, value in sorted(by_term.items())},
        "dependents": {key: sorted(set(value)) for key, value in sorted(dependents.items())},
        "derived_ids": sorted(set(derived_ids)),
        "bucket_positions": bucket_positions,
    }


def knowledge_index_is_current(pack: dict[str, Any]) -> bool:
    index = pack.get("knowledge_index")
    return bool(
        isinstance(index, dict)
        and index.get("kind") == "KnowledgeIndex"
        and index.get("schema_version") == "1.0"
        and int(index.get("pack_revision", -1)) == int(pack.get("knowledge_revision", 0))
        and int(index.get("item_count", -1)) == len(pack.get("all_items", []))
    )


def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        IMPORTANCE_RANK.get(item.get("importance"), 9),
        NEED_RANK.get(item.get("need_state"), 9),
        str(item.get("type", "")),
        str(item.get("id", "")),
    )


def _sorted_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=_sort_key)


def _active(item: dict[str, Any]) -> bool:
    return (
        item.get("status", "active") == "active"
        and item.get("retention") != "discard"
        and item.get("review_state") != "rejected"
        and item.get("importance") != "noise"
        and item.get("derived_state", "fresh") != "stale"
    )


def rebuild_pack_indexes(pack: dict[str, Any]) -> dict[str, Any]:
    all_items = _sorted_items([dict(row) for row in pack.get("all_items", [])])
    pack["all_items"] = all_items
    for bucket in ACTIVE_BUCKETS.values():
        pack[bucket] = []
    for item in all_items:
        if _active(item):
            bucket = ACTIVE_BUCKETS.get(item.get("type"))
            if bucket:
                pack[bucket].append(item)
    pack["archived_items"] = _sorted_items(
        list({row["id"]: row for row in pack.get("archived_items", []) + [row for row in all_items if row.get("status") == "archived" or row.get("retention") == "archive"]}.values())
    )
    pack["discarded_items"] = _sorted_items(
        list({row["id"]: row for row in pack.get("discarded_items", []) + [row for row in all_items if row.get("retention") == "discard"]}.values())
    )
    pack.setdefault("knowledge_revision", 0)
    pack["knowledge_index"] = build_knowledge_index(pack)
    return pack


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
    return rebuild_pack_indexes(pack)


def load_project_knowledge(path: str | pathlib.Path) -> dict[str, Any]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return rebuild_pack_indexes(data)


def save_project_knowledge(path: str | pathlib.Path, pack: dict[str, Any]) -> dict[str, Any]:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = rebuild_pack_indexes(dict(pack))
    target.write_text(json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"kind": "KnowledgeStoreWriteResult", "path": str(target), "pack": clean, "diagnostics": []}


def upsert_knowledge_items(pack: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(pack or new_project_knowledge_pack("CGKN"))
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
    return rebuild_pack_indexes(out)


def archive_knowledge_item(pack: dict[str, Any], item_id: str, reason: str | None = None) -> dict[str, Any]:
    out = dict(pack)
    for item in out.get("all_items", []):
        if item.get("id") == item_id:
            item["status"] = "archived"
            item["retention"] = "archive"
            item.setdefault("diagnostics", []).append({"code": "CGNK_KNOWLEDGE_SUPERSEDED", "severity": "info", "message": reason or "archived"})
            out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
    return rebuild_pack_indexes(out)


def discard_knowledge_item(pack: dict[str, Any], item_id: str, reason: str | None = None) -> dict[str, Any]:
    out = dict(pack)
    for item in out.get("all_items", []):
        if item.get("id") == item_id:
            item["retention"] = "discard"
            item.setdefault("diagnostics", []).append({"code": "CGNK_KNOWLEDGE_DISCARDED", "severity": "info", "message": reason or "discarded"})
            out["knowledge_revision"] = int(out.get("knowledge_revision", 0)) + 1
    return rebuild_pack_indexes(out)
