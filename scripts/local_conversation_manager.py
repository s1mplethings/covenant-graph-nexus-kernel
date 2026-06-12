#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONVERSATION_ROOT = ROOT / "examples" / "local_studio" / "conversations"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_id(raw: Any) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "")).strip("-")
    return value[:120] or "conversation"


def conversation_root() -> pathlib.Path:
    override = str(os.environ.get("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", "")).strip()
    return pathlib.Path(override) if override else DEFAULT_CONVERSATION_ROOT


def conversation_dir(conversation_id: str) -> pathlib.Path:
    return conversation_root() / safe_id(conversation_id)


def conversation_path(conversation_id: str) -> pathlib.Path:
    return conversation_dir(conversation_id) / "conversation.json"


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False) + "\n")


def empty_active_project() -> dict[str, Any]:
    return {
        "kind": "CGNKActiveProject",
        "project_id": "",
        "project_dir": "",
        "current_worktree": "",
        "latest_delivery_manifest": "",
        "latest_project_package": "",
        "revision_index": 0,
        "latest_revision_manifest": "",
        "status": "none",
    }


def default_whiteboard() -> dict[str, Any]:
    return {
        "project_summary": "",
        "known_facts": [],
        "open_questions": [],
        "default_assumptions": [],
        "first_version_plan": [],
        "blocking_questions": [],
        "user_rules": [],
        "acceptance_criteria": [],
        "change_requests": [],
        "decision_log": [],
        "delivery_requirements": [],
        "ready_to_generate": False,
    }


def default_conversation(conversation_id: str, source: str = "local") -> dict[str, Any]:
    created = now()
    return {
        "kind": "CGNKConversation",
        "schema_version": "1",
        "conversation_id": safe_id(conversation_id),
        "source": source,
        "created_at": created,
        "updated_at": created,
        "messages": [],
        "attachments": [],
        "memory_events": [],
        "whiteboard_versions": [],
        "whiteboard": default_whiteboard(),
        "generation": {"status": "idle"},
        "active_run": None,
        "active_project": empty_active_project(),
        "revision_history": [],
        "pending_decision": None,
    }


def normalize_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    conversation.setdefault("kind", "CGNKConversation")
    conversation.setdefault("schema_version", "1")
    conversation["conversation_id"] = safe_id(conversation.get("conversation_id", "conversation"))
    conversation.setdefault("source", "local")
    conversation.setdefault("created_at", now())
    conversation.setdefault("updated_at", now())
    conversation.setdefault("messages", [])
    conversation.setdefault("attachments", [])
    conversation.setdefault("memory_events", [])
    conversation.setdefault("whiteboard_versions", [])
    conversation.setdefault("whiteboard", default_whiteboard())
    conversation.setdefault("generation", {"status": "idle"})
    conversation.setdefault("active_run", None)
    conversation.setdefault("active_project", empty_active_project())
    conversation.setdefault("revision_history", [])
    conversation.setdefault("pending_decision", None)
    return conversation


def load_conversation(conversation_id: str) -> dict[str, Any]:
    path = conversation_path(conversation_id)
    if not path.exists():
        return default_conversation(conversation_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_conversation(conversation_id)
    return normalize_conversation(doc if isinstance(doc, dict) else default_conversation(conversation_id))


def save_conversation(conversation: dict[str, Any]) -> None:
    normalize_conversation(conversation)
    conversation["updated_at"] = now()
    base = conversation_dir(str(conversation.get("conversation_id", "")))
    write_json(base / "conversation.json", conversation)


def append_user_message(
    conversation: dict[str, Any],
    text: str,
    source: str = "local",
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalize_conversation(conversation)
    message = {
        "role": "user",
        "text": str(text or ""),
        "source": source,
        "attachments": attachments or [],
        "created_at": now(),
    }
    conversation["messages"].append(message)
    if attachments:
        conversation["attachments"].extend(attachments)
    append_jsonl(conversation_dir(conversation["conversation_id"]) / "messages.jsonl", message)
    return message


def append_assistant_message(
    conversation: dict[str, Any],
    text: str,
    event: str = "",
    source: str = "main_agent_manager",
) -> dict[str, Any]:
    normalize_conversation(conversation)
    message = {
        "role": "assistant",
        "text": str(text or ""),
        "event": event,
        "source": source,
        "created_at": now(),
    }
    conversation["messages"].append(message)
    append_jsonl(conversation_dir(conversation["conversation_id"]) / "messages.jsonl", message)
    return message


def update_whiteboard(conversation: dict[str, Any], patch: dict[str, Any], reason: str) -> dict[str, Any]:
    normalize_conversation(conversation)
    whiteboard = conversation.get("whiteboard", {})
    if not isinstance(whiteboard, dict):
        whiteboard = default_whiteboard()
    for key, value in patch.items():
        if isinstance(value, list):
            existing = whiteboard.get(key, [])
            existing_items = existing if isinstance(existing, list) else []
            seen = {str(item) for item in existing_items}
            merged = list(existing_items)
            for item in value:
                marker = str(item)
                if marker and marker not in seen:
                    merged.append(item)
                    seen.add(marker)
            whiteboard[key] = merged
        elif isinstance(value, dict) and isinstance(whiteboard.get(key), dict):
            nested = dict(whiteboard.get(key, {}))
            nested.update(value)
            whiteboard[key] = nested
        else:
            whiteboard[key] = value
    event = {"created_at": now(), "reason": reason, "whiteboard": whiteboard}
    conversation["whiteboard"] = whiteboard
    conversation["whiteboard_versions"].append(event)
    append_jsonl(conversation_dir(conversation["conversation_id"]) / "whiteboard_versions.jsonl", event)
    return whiteboard


def get_active_project(conversation: dict[str, Any]) -> dict[str, Any]:
    normalize_conversation(conversation)
    active = conversation.get("active_project")
    return active if isinstance(active, dict) else empty_active_project()


def bind_active_project(conversation: dict[str, Any], active_project: dict[str, Any]) -> dict[str, Any]:
    normalize_conversation(conversation)
    bound = empty_active_project()
    bound.update(active_project)
    bound["kind"] = "CGNKActiveProject"
    conversation["active_project"] = bound
    write_json(conversation_dir(conversation["conversation_id"]) / "active_project.json", bound)
    return bound


def append_revision_history(conversation: dict[str, Any], revision_manifest: dict[str, Any]) -> dict[str, Any]:
    normalize_conversation(conversation)
    conversation["revision_history"].append(revision_manifest)
    append_jsonl(conversation_dir(conversation["conversation_id"]) / "revision_history.jsonl", revision_manifest)
    return revision_manifest


def conversation_summary(conversation: dict[str, Any]) -> dict[str, Any]:
    normalize_conversation(conversation)
    active = get_active_project(conversation)
    return {
        "conversation_id": conversation["conversation_id"],
        "source": conversation.get("source", "local"),
        "message_count": len(conversation.get("messages", [])),
        "active_project_id": active.get("project_id", ""),
        "active_project_status": active.get("status", "none"),
        "revision_index": active.get("revision_index", 0),
        "generation_status": conversation.get("generation", {}).get("status", "idle") if isinstance(conversation.get("generation"), dict) else "idle",
    }
