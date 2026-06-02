from __future__ import annotations

import hashlib
from typing import Any

from .event_log import append_event
from .keypoint_extract import extract_keypoints_from_turn
from .normalize import normalize_keypoints_to_knowledge_items
from .reporting import build_knowledge_update_report
from .store import new_project_knowledge_pack, upsert_knowledge_items


def _event_id(session_id: str, turn_index: int, event_type: str, content: str) -> str:
    seed = f"{session_id}|{turn_index}|{event_type}|{content}"
    return "evt_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _summary(text: str, limit: int = 240) -> str:
    value = " ".join(str(text or "").split())
    return value[: limit - 3] + "..." if len(value) > limit else value


def _make_event(session_id: str, turn_index: int, event_type: str, content: str, artifact_refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "kind": "ConversationEvent",
        "event_id": _event_id(session_id, turn_index, event_type, content),
        "session_id": session_id,
        "turn_index": turn_index,
        "type": event_type,
        "content_summary": _summary(content),
        "artifact_refs": artifact_refs or [],
        "diagnostics": [],
    }


def update_knowledge_from_dialogue_turn(
    session_state: dict[str, Any] | None,
    user_message: str,
    assistant_message: str | None = None,
    pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = session_state or {}
    session_id = str(state.get("session_id") or state.get("run_id") or "session")
    turn_index = int(state.get("turn_index") or state.get("turn_count") or 0) + 1
    events: list[dict[str, Any]] = []
    log = state.get("event_log", [])
    user_event = _make_event(session_id, turn_index, "user.message", user_message, list(state.get("artifact_refs", [])) if isinstance(state.get("artifact_refs"), list) else [])
    log_result = append_event(log, user_event)
    events.append(user_event)
    log = log_result["events"]
    if assistant_message:
        assistant_event = _make_event(session_id, turn_index, "assistant.message", assistant_message)
        log_result = append_event(log, assistant_event)
        events.append(assistant_event)
        log = log_result["events"]
    state = dict(state)
    state["current_event_ids"] = [event["event_id"] for event in events]
    extraction = extract_keypoints_from_turn(state, user_message, assistant_message)
    target_pack = pack or new_project_knowledge_pack(str(state.get("project") or "CGNK"))
    existing_items = target_pack.get("all_items", [])
    normalization = normalize_keypoints_to_knowledge_items(extraction["keypoints"], existing_items=existing_items)
    upsert_items = normalization["items"] + normalization["updated_existing_items"] + normalization["superseded"]
    updated_pack = upsert_knowledge_items(target_pack, upsert_items)
    report = build_knowledge_update_report(
        events,
        extraction["keypoints"],
        normalization["items"],
        updated_pack,
        updated_items=normalization["updated_existing_items"],
        superseded_items=normalization["superseded"],
        discarded_items=updated_pack.get("discarded_items", []),
        diagnostics=log_result.get("diagnostics", []) + extraction.get("diagnostics", []) + normalization.get("diagnostics", []),
    )
    return {
        "kind": "KnowledgeDialogueUpdateResult",
        "events": events,
        "event_log": log,
        "keypoints": extraction["keypoints"],
        "items": normalization["items"],
        "pack": updated_pack,
        "report": report,
        "diagnostics": report["diagnostics"],
    }
