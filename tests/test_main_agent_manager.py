from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_conversation_manager as conversations
from scripts import project_revision_lane
from scripts.main_agent_manager import MainAgentManager


def test_new_project_request_records_provider_route_requirement(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))

    result = MainAgentManager().handle_user_turn("chat-main", "做一个本地视觉小说编辑器", source="local_cli")

    assert result["intent"] == "new_project_request"
    assert result["provider_route_required"] is True
    loaded = conversations.load_conversation("chat-main")
    assert loaded["generation"]["provider_route_required"] is True


def test_active_project_change_routes_to_revision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('v0')\n", encoding="utf-8")
    conversation = conversations.default_conversation("chat-main")
    project_revision_lane.bind_initial_project_delivery(conversation, source, "final_project_bundle.zip", "delivery_manifest.json")
    conversations.save_conversation(conversation)

    result = MainAgentManager().handle_user_turn("chat-main", "把上次那个项目加一个导出按钮", source="local_cli")

    assert result["intent"] == "project_revision_request"
    assert result["status"] == "revision_prepared"
    assert pathlib.Path(result["revision_manifest"]).exists()


def test_explicit_new_project_is_not_revision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    monkeypatch.setenv("CGNK_MANAGED_PROJECT_ROOT", str(tmp_path / "managed"))
    conversation = conversations.default_conversation("chat-main")
    conversations.bind_active_project(conversation, {"project_id": "project-chat-main", "status": "delivered"})

    intent = MainAgentManager().classify_intent(conversation, "开新项目，不要沿用上次")
    assert intent["intent"] == "new_project_request"


def test_status_query_does_not_start_generation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    result = MainAgentManager().handle_user_turn("chat-status", "现在状态怎么样", source="local_cli")
    assert result["intent"] == "status_query"
    assert "provider_route_required" not in result


def test_model_selection_comes_from_model_policy(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_REVIEW_MODEL", "review-test")
    assert MainAgentManager().choose_model("review") == "review-test"


def test_manager_source_does_not_call_legacy_mainline() -> None:
    text = (ROOT / "scripts" / "main_agent_manager.py").read_text(encoding="utf-8")
    assert "run_local_pipeline" not in text
    assert "generate_project.py" not in text
    assert "simulator" not in text
