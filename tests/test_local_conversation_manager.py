from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_conversation_manager as conversations


def test_create_append_bind_and_reload_conversation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))

    conversation = conversations.default_conversation("chat one", source="telegram")
    assert conversation["active_project"]["status"] == "none"

    conversations.append_user_message(conversation, "做一个本地工具", source="telegram")
    conversations.append_assistant_message(conversation, "已记录", event="recorded")
    conversations.update_whiteboard(conversation, {"known_facts": ["本地工具"], "project_summary": "本地工具"}, "test")
    conversations.bind_active_project(
        conversation,
        {
            "project_id": "project-chat-one",
            "current_worktree": "generated/managed_projects/project-chat-one/current",
            "status": "delivered",
        },
    )
    conversations.append_revision_history(conversation, {"kind": "ProjectRevisionManifest", "revision_index": 1})
    conversations.save_conversation(conversation)

    loaded = conversations.load_conversation("chat one")
    assert loaded["source"] == "telegram"
    assert len(loaded["messages"]) == 2
    assert loaded["whiteboard"]["project_summary"] == "本地工具"
    assert loaded["active_project"]["project_id"] == "project-chat-one"
    assert loaded["revision_history"][0]["revision_index"] == 1


def test_conversation_summary_uses_shared_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    conversation = conversations.default_conversation("local-chat", source="local_cli")
    summary = conversations.conversation_summary(conversation)
    assert summary["conversation_id"] == "local-chat"
    assert summary["source"] == "local_cli"
    assert summary["active_project_status"] == "none"
