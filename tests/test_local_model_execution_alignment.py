from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge


FORBIDDEN_PUBLIC = ("provider", "api", "403", "quota", "TLS", "SSL", "traceback", "exception")


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))


def seed_project(session_dir: pathlib.Path, chat_id: str = "chat-local") -> None:
    session = bridge.default_session(chat_id)
    session["whiteboard"]["project_summary"] = "做一个本地项目生成系统，像项目团队一样交付"
    session["active_run"] = {"id": f"run-{chat_id}", "status": "intake_open", "goal": session["whiteboard"]["project_summary"]}
    bridge.save_session(session_dir, session)


def assert_public_clean(text: str) -> None:
    lowered = text.lower()
    for term in FORBIDDEN_PUBLIC:
        assert term.lower() not in lowered


def test_target_project_local_model_request_starts_current_cgkn_backend(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        seed_project(session_dir)
        client = FakeTelegramClient()
        monkeypatch.setattr(bridge, "local_project_generation_available", lambda: False)
        started: dict[str, object] = {}

        def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
            session = bridge.load_session(session_dir_arg, chat_id)
            started["called"] = True
            started["requested"] = session["generation"].get("requested_generation_mode")
            started["effective"] = session["generation"].get("effective_generation_mode")
            session["generation"]["status"] = "running"
            bridge.save_session(session_dir_arg, session)

        monkeypatch.setattr(bridge, "start_agent_generation", fake_start)

        bridge.handle_text(client, "chat-local", "走本地模型 + 开始做吧", session_dir, log_dir, "gpt-test", 60, generation_mode="api")

        session = bridge.load_session(session_dir, "chat-local")
        assert started["called"] is True
        assert started["requested"] == "api"
        assert started["effective"] == "api"
        assert session["generation"]["status"] == "running"
        assert session["whiteboard"]["target_project_architecture"]["model_mode"] == "local_model"
        assert session["whiteboard"]["cgkn_execution"]["generation_backend"] == "api"
        assert "本地模型路线设计" in client.messages[-1][1]
        assert "当前可用的生成后端" in client.messages[-1][1]
        assert "还没有确认可用" not in client.messages[-1][1]
        assert_public_clean(client.messages[-1][1])


def test_explicit_platform_no_api_blocks_when_local_backend_unavailable(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        seed_project(session_dir)
        client = FakeTelegramClient()
        monkeypatch.setattr(bridge, "local_project_generation_available", lambda: False)
        monkeypatch.setattr(
            bridge,
            "start_agent_generation",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("platform no-api constraint must not use api generation")),
        )

        bridge.handle_text(client, "chat-local", "你们生成代码不要走 API，走本地模型 + 开始做吧", session_dir, log_dir, "gpt-test", 60, generation_mode="api")

        session = bridge.load_session(session_dir, "chat-local")
        assert session["generation"]["requested_generation_mode"] == "local"
        assert session["generation"]["effective_generation_mode"] == "none"
        assert session["generation"]["status"] == "generation_blocked_by_local_model_config"
        assert session["whiteboard"]["target_project_architecture"]["model_mode"] == "local_model"
        assert session["whiteboard"]["cgkn_execution"]["platform_no_api"] is True
        assert_public_clean(client.messages[-1][1])


def test_api_generation_after_local_block_requires_user_confirmation(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        seed_project(session_dir)
        client = FakeTelegramClient()
        monkeypatch.setattr(bridge, "local_project_generation_available", lambda: False)
        started: dict[str, object] = {}

        def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
            session = bridge.load_session(session_dir_arg, chat_id)
            started["requested"] = session["generation"].get("requested_generation_mode")
            started["effective"] = session["generation"].get("effective_generation_mode")
            started["fallback_explicit"] = session["generation"].get("local_to_api_fallback_explicit")
            session["generation"]["status"] = "running"
            bridge.save_session(session_dir_arg, session)

        monkeypatch.setattr(bridge, "start_agent_generation", fake_start)

        bridge.handle_text(client, "chat-local", "你们生成代码不要走 API，走本地模型 + 开始做吧", session_dir, log_dir, "gpt-test", 60, generation_mode="api")
        assert started == {}
        blocked = bridge.load_session(session_dir, "chat-local")
        blocked_run_id = blocked["active_run"]["id"]

        bridge.handle_text(client, "chat-local", "那怎么办？", session_dir, log_dir, "gpt-test", 60, generation_mode="api")
        after_question = bridge.load_session(session_dir, "chat-local")
        assert started == {}
        assert after_question["generation"]["requested_generation_mode"] == "local"
        assert after_question["generation"]["effective_generation_mode"] == "none"
        assert after_question["generation"]["status"] == "generation_blocked_by_local_model_config"
        assert after_question["active_run"]["id"] == blocked_run_id
        assert "明确" in client.messages[-1][1]
        assert "当前可用生成方式" in client.messages[-1][1]
        assert "接口生成" not in client.messages[-1][1]
        assert "不会" in client.messages[-1][1]
        assert_public_clean(client.messages[-1][1])

        bridge.handle_text(client, "chat-local", "继续生成", session_dir, log_dir, "gpt-test", 60, generation_mode="api")

        assert started["requested"] == "local"
        assert started["effective"] == "api"
        assert started["fallback_explicit"] is True
        switched = bridge.load_session(session_dir, "chat-local")
        assert switched["active_run"]["id"] == blocked_run_id
        assert switched["whiteboard"]["local_to_api_fallback_explicit"] is True
        assert any("明确允许" in item for item in switched["whiteboard"].get("known_facts", []))
        assert "接口生成" not in client.messages[-1][1]
        assert "不另开项目" in client.messages[-1][1]


def test_running_evidence_repair_is_recorded_without_new_project(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        seed_project(session_dir)
        session = bridge.load_session(session_dir, "chat-local")
        session["generation"] = {"status": "running", "driver": "api_provider_project_generation"}
        session["active_run"] = {"id": "run-chat-local", "status": "running", "goal": session["whiteboard"]["project_summary"]}
        bridge.save_session(session_dir, session)
        client = FakeTelegramClient()
        monkeypatch.setattr(
            bridge,
            "start_agent_generation",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("repair request should not start a new generation")),
        )
        monkeypatch.setattr(bridge, "provider_user_message", lambda *args, **kwargs: "")

        bridge.handle_text(client, "chat-local", "那先补截图和测试", session_dir, log_dir, "gpt-test", 60)

        saved = bridge.load_session(session_dir, "chat-local")
        assert saved["generation"]["status"] == "running"
        assert saved["active_run"]["id"] == "run-chat-local"
        assert saved["active_run"]["next_action"] == "repair_evidence"
        assert any(event.get("type") == "evidence_repair_requested" for event in saved.get("memory_events", []))


def test_default_api_mode_does_not_claim_local_model(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        seed_project(session_dir)
        client = FakeTelegramClient()

        def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
            session = bridge.load_session(session_dir_arg, chat_id)
            session["generation"]["status"] = "running"
            bridge.save_session(session_dir_arg, session)

        monkeypatch.setattr(bridge, "start_agent_generation", fake_start)

        bridge.handle_text(client, "chat-local", "开始生成", session_dir, log_dir, "gpt-test", 60, generation_mode="api")

        session = bridge.load_session(session_dir, "chat-local")
        assert session["generation"]["requested_generation_mode"] == "api"
        assert session["generation"]["effective_generation_mode"] == "api"
        assert "本地模型路线" not in client.messages[-1][1]
        assert "本地模型生成" not in client.messages[-1][1]


def test_evidence_repair_request_marks_same_context_repair(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        seed_project(session_dir)
        session = bridge.load_session(session_dir, "chat-local")
        session["generation"] = {"status": "rework_blocked", "driver": "api_provider_project_generation"}
        session["active_run"] = {"id": "run-chat-local", "status": "rework_blocked", "goal": session["whiteboard"]["project_summary"]}
        bridge.save_session(session_dir, session)
        client = FakeTelegramClient()
        monkeypatch.setattr(
            bridge,
            "start_agent_generation",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("repair request should not start a new generation")),
        )
        monkeypatch.setattr(bridge, "provider_user_message", lambda *args, **kwargs: "对，下一步先补截图和测试；补齐前不能算完成。")

        bridge.handle_text(client, "chat-local", "那先补截图和测试", session_dir, log_dir, "gpt-test", 60)

        saved = bridge.load_session(session_dir, "chat-local")
        assert saved["generation"]["status"] == "evidence_repair_requested"
        assert saved["active_run"]["next_action"] == "repair_evidence"
        assert saved["active_run"]["id"] == "run-chat-local"
        assert "那先补截图和测试" in "\n".join(saved["whiteboard"].get("change_requests", []))
        assert "还不能交付" in client.messages[-1][1] or "不能算完成" in client.messages[-1][1]


def test_evidence_gap_question_does_not_start_generation(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        seed_project(session_dir)
        session = bridge.load_session(session_dir, "chat-local")
        session["generation"] = {"status": "running", "driver": "api_provider_project_generation"}
        bridge.save_session(session_dir, session)
        client = FakeTelegramClient()
        monkeypatch.setattr(
            bridge,
            "start_agent_generation",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("status question must not start generation")),
        )
        monkeypatch.setattr(bridge, "provider_user_message", lambda *args, **kwargs: "还没有截图，因为还没拿到可验证的界面预览。")

        bridge.handle_text(client, "chat-local", "为什么还没有截图", session_dir, log_dir, "gpt-test", 60)

        saved = bridge.load_session(session_dir, "chat-local")
        assert saved["messages"][-1]["event"] == "status_requested"
        assert saved["generation"]["status"] == "running"
