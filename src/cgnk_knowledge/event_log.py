from __future__ import annotations

import json
from typing import Any


ALLOWED_EVENT_TYPES = {
    "user.message",
    "assistant.message",
    "backend.intent.updated",
    "backend.planning.preview",
    "backend.agent.generated",
    "backend.research.result",
    "backend.agent.message",
    "artifact.created",
    "gate.required",
    "gate.resolved",
    "knowledge.updated",
}

REQUIRED_FIELDS = ("kind", "event_id", "session_id", "turn_index", "type", "content_summary", "artifact_refs", "diagnostics")


def _diag(message: str, path: str = "event") -> dict[str, str]:
    return {"code": "CGNK_KNOWLEDGE_EVENT_INVALID", "severity": "warning", "path": path, "message": message}


def _validate_event(event: dict[str, Any]) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    for field in REQUIRED_FIELDS:
        if field not in event:
            diagnostics.append(_diag(f"missing required field: {field}", field))
    if event.get("kind") != "ConversationEvent":
        diagnostics.append(_diag("kind must be ConversationEvent", "kind"))
    if event.get("type") not in ALLOWED_EVENT_TYPES:
        diagnostics.append(_diag("event type is not allowed", "type"))
    if not isinstance(event.get("artifact_refs", []), list):
        diagnostics.append(_diag("artifact_refs must be a list", "artifact_refs"))
    if not isinstance(event.get("diagnostics", []), list):
        diagnostics.append(_diag("diagnostics must be a list", "diagnostics"))
    return diagnostics


def append_event(log: list[dict[str, Any]] | dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    events = list(log.get("events", []) if isinstance(log, dict) else (log or []))
    item = dict(event)
    item.setdefault("kind", "ConversationEvent")
    item.setdefault("artifact_refs", [])
    item.setdefault("diagnostics", [])
    diagnostics = _validate_event(item)
    if diagnostics:
        item["diagnostics"] = list(item.get("diagnostics", [])) + diagnostics
    events.append(item)
    events.sort(key=lambda row: (str(row.get("session_id", "")), int(row.get("turn_index", 0)), str(row.get("event_id", ""))))
    return {"kind": "ConversationEventLog", "events": events, "diagnostics": diagnostics}


def list_events(log: list[dict[str, Any]] | dict[str, Any] | None, session_id: str | None = None) -> list[dict[str, Any]]:
    events = list(log.get("events", []) if isinstance(log, dict) else (log or []))
    if session_id is not None:
        events = [row for row in events if row.get("session_id") == session_id]
    return sorted(events, key=lambda row: (str(row.get("session_id", "")), int(row.get("turn_index", 0)), str(row.get("event_id", ""))))


def events_to_jsonl(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in list_events(events)) + ("\n" if events else "")


def events_from_jsonl(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return list_events(rows)
