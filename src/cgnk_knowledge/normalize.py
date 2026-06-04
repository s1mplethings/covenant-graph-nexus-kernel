from __future__ import annotations

import hashlib
import re
from typing import Any


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def stable_hash_for(content: str, item_type: str, scope: str) -> str:
    seed = f"{scope}|{item_type}|{normalize_text(content)}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _item_id(stable_hash: str) -> str:
    return f"ki_{stable_hash[:12]}"


def _title(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    return value[:77] + "..." if len(value) > 80 else value


def _knowledge_item_from_keypoint(keypoint: dict[str, Any]) -> dict[str, Any]:
    item_type = keypoint.get("category", "requirement")
    scope = keypoint.get("scope", "project")
    content = keypoint.get("text", "")
    stable_hash = stable_hash_for(content, item_type, scope)
    return {
        "kind": "KnowledgeItem",
        "id": _item_id(stable_hash),
        "title": _title(content),
        "type": item_type,
        "scope": scope,
        "content": content,
        "source_refs": list(keypoint.get("source_event_ids", [])),
        "tags": sorted(set(keypoint.get("tags", []))),
        "importance": keypoint.get("importance", "medium"),
        "need_state": keypoint.get("need_state", "unknown"),
        "retention": keypoint.get("retention", "keep"),
        "review_state": keypoint.get("review_state", "auto_extracted"),
        "status": keypoint.get("status", "active"),
        "supersedes": [],
        "stable_hash": stable_hash,
        "diagnostics": list(keypoint.get("diagnostics", [])),
    }


def _cgkn_write_allowed(text: str) -> bool:
    lowered = normalize_text(text)
    return "cgkn" in lowered and any(phrase in lowered for phrase in ("may be modified", "can modify", "work in cgkn", "directly work in cgkn", "修改 cgkn"))


def _cgkn_read_only(text: str) -> bool:
    lowered = normalize_text(text)
    return "cgkn" in lowered and any(phrase in lowered for phrase in ("read-only", "只读", "do not modify cgkn", "no cgkn modification", "不要改 cgkn"))


def _cgnk_only(text: str) -> bool:
    lowered = normalize_text(text)
    return "cgnk only" in lowered or "cgkn only" in lowered or "work in cgnk only" in lowered or "working in cgnk only" in lowered


def _supersedes(new_item: dict[str, Any], old_item: dict[str, Any]) -> bool:
    new_text = new_item.get("content", "")
    old_text = old_item.get("content", "")
    if _cgkn_read_only(new_text) and _cgkn_write_allowed(old_text):
        return True
    if _cgnk_only(new_text) and _cgkn_write_allowed(old_text):
        return True
    return False


def normalize_keypoints_to_knowledge_items(keypoints: list[dict[str, Any]], existing_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    existing = [dict(row) for row in (existing_items or [])]
    by_hash: dict[str, dict[str, Any]] = {str(row.get("stable_hash", "")): row for row in existing if row.get("stable_hash")}
    items: list[dict[str, Any]] = []
    updated_existing: list[dict[str, Any]] = []
    deduped: list[dict[str, Any]] = []
    superseded: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for keypoint in sorted(keypoints, key=lambda row: str(row.get("id", ""))):
        item = _knowledge_item_from_keypoint(keypoint)
        found = by_hash.get(item["stable_hash"])
        if found:
            merged = dict(found)
            merged["source_refs"] = sorted(set(merged.get("source_refs", []) + item.get("source_refs", [])))
            merged["tags"] = sorted(set(merged.get("tags", []) + item.get("tags", [])))
            updated_existing.append(merged)
            by_hash[item["stable_hash"]] = merged
            deduped.append({"stable_hash": item["stable_hash"], "existing_id": merged["id"], "keypoint_id": keypoint.get("id")})
            diagnostics.append({"code": "CGNK_KNOWLEDGE_DEDUPE_APPLIED", "severity": "info", "message": "duplicate knowledge item merged"})
            continue
        for old in existing + items:
            if old.get("status", "active") == "active" and _supersedes(item, old):
                old["status"] = "superseded"
                old["review_state"] = "rejected"
                old["need_state"] = "not_needed"
                old["retention"] = "archive"
                old["superseded_by"] = item["id"]
                item["supersedes"].append(old["id"])
                superseded.append(old)
                diagnostics.append({"code": "CGNK_KNOWLEDGE_SUPERSEDED", "severity": "info", "message": f"{item['id']} superseded {old['id']}"})
        items.append(item)
        by_hash[item["stable_hash"]] = item

    return {
        "kind": "KnowledgeNormalizationResult",
        "items": sorted(items, key=lambda row: row["id"]),
        "updated_existing_items": sorted(updated_existing, key=lambda row: row["id"]),
        "deduped": deduped,
        "superseded": sorted(superseded, key=lambda row: row["id"]),
        "diagnostics": diagnostics,
    }
