from __future__ import annotations

import pathlib
import tempfile

import scripts.codex_conversation as bridge
from scripts import model_mode_semantics


def test_target_project_model_mode_is_separate_from_generation_backend() -> None:
    session = bridge.default_session("alignment")
    session["whiteboard"]["project_summary"] = "本地项目生成系统"

    model_mode_semantics.apply_model_mode_semantics(
        session,
        "目标项目使用本地模型",
        configured_backend_mode="api",
        configured_model="gpt-test",
    )

    assert session["whiteboard"]["target_project_architecture"]["model_mode"] == "local_model"
    assert session["whiteboard"]["cgkn_execution"]["generation_backend"] == "api"


def test_platform_no_api_constraint_does_not_reconnect_removed_local_generator() -> None:
    session = bridge.default_session("alignment")
    session["whiteboard"]["project_summary"] = "本地项目生成系统"

    model_mode_semantics.apply_model_mode_semantics(
        session,
        "你们生成代码不要走 API，目标项目使用本地模型",
        configured_backend_mode="api",
        configured_model="gpt-test",
    )

    assert session["whiteboard"]["cgkn_execution"]["platform_no_api"] is True
    assert session["whiteboard"]["cgkn_execution"]["platform_generation_constraint"] == "local"
    assert not hasattr(bridge, "local_project_generation_available")


def test_status_question_does_not_start_generation(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        session = bridge.default_session("chat-local")
        session["whiteboard"]["project_summary"] = "本地项目生成系统"
        session["active_run"] = {"id": "run-chat-local", "status": "running", "goal": "本地项目生成系统"}
        session["generation"] = {"status": "running", "driver": "api_provider_project_generation"}
        bridge.save_session(session_dir, session)

        class Client:
            def send_message(self, conversation_id, text):
                return True

            def send_chat_action(self, conversation_id, action):
                return None

        monkeypatch.setattr(
            bridge,
            "start_agent_generation",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("status query must not start generation")),
        )
        monkeypatch.setattr(bridge, "provider_user_message", lambda *args, **kwargs: "界面证据仍在补充。")

        bridge.handle_text(Client(), "chat-local", "现在进度怎么样", session_dir, log_dir, "gpt-test", 60)
        saved = bridge.load_session(session_dir, "chat-local")

    assert saved["generation"]["status"] == "running"
    assert saved["active_run"]["id"] == "run-chat-local"
