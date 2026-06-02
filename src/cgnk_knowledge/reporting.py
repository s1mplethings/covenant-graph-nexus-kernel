from __future__ import annotations

from typing import Any


def build_knowledge_update_report(
    events: list[dict[str, Any]],
    keypoints: list[dict[str, Any]],
    items: list[dict[str, Any]],
    pack: dict[str, Any] | None = None,
    updated_items: list[dict[str, Any]] | None = None,
    superseded_items: list[dict[str, Any]] | None = None,
    discarded_items: list[dict[str, Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    all_diags = list(diagnostics or [])
    review_required = [row for row in keypoints if row.get("review_state") in {"candidate", "conflict"}]
    if review_required:
        all_diags.append({"code": "CGNK_KNOWLEDGE_REVIEW_REQUIRED", "severity": "warning", "message": "knowledge review required"})
    return {
        "kind": "KnowledgeUpdateReport",
        "events": events,
        "added_keypoints": keypoints,
        "added_items": items,
        "updated_items": updated_items or [],
        "superseded_items": superseded_items or [],
        "discarded_items": discarded_items or [],
        "critical_updates": [row for row in items if row.get("importance") == "critical"],
        "needed_now": [row for row in items if row.get("need_state") == "needed_now"],
        "review_required": review_required,
        "diagnostics": all_diags,
    }
