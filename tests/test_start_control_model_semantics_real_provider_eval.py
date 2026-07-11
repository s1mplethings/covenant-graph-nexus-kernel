from __future__ import annotations

import pathlib
import tempfile

import pytest

import scripts.telegram_live_bridge as bridge

pytestmark = [pytest.mark.provider, pytest.mark.telegram, pytest.mark.e2e]


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True


def _patch_dialogue(monkeypatch):
    def fake_analysis(session_dir, chat_id, session, *, model, timeout, reason):
        latest = bridge.latest_user_text(session)
        whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
        summary = str(whiteboard.get("project_summary") or "").strip()
        known = list(whiteboard.get("known_facts", []) if isinstance(whiteboard.get("known_facts"), list) else [])
        if "工具" in latest and not summary:
            summary = "小团队本地任务和项目资料管理工具"
        elif "小团队" in latest:
            summary = "小团队本地任务和项目资料管理工具"
        elif "本地运行" in latest:
            summary = "本地运行的小团队任务和项目资料管理工具"
        elif "任务" in latest and "项目资料" in latest:
            summary = "本地运行的小团队任务管理和项目资料管理工具"
        elif "AI 文档助手" in latest:
            summary = "本地 AI 文档助手，支持导入、检索、总结和界面"
            whiteboard["target_project_architecture"] = {"model_mode": "local_model"}
            whiteboard["cgkn_execution"] = {"generation_backend": "api"}
        if latest:
            known.append(f"用户补充: {latest}")
        whiteboard["project_summary"] = summary or latest
        whiteboard["known_facts"] = bridge.unique_strings(known)
        whiteboard.setdefault("open_questions", ["第一版优先任务、资料还是搜索？"])
        whiteboard.setdefault("delivery_requirements", ["可运行项目", "截图", "测试报告"])
        session["whiteboard"] = whiteboard
        bridge.save_session(session_dir, session)
        return {
            "status": "ok",
            "reason": reason,
            "project_summary": whiteboard["project_summary"],
            "soft_questions": whiteboard.get("open_questions", [])[:2],
            "critical_questions": [],
            "missing_required_inputs": [],
            "confidence": 0.9,
            "user_visible_reply": "我会先收敛第一版范围。",
        }

    def fake_customer_reply(session, model, timeout):
        latest = bridge.latest_user_text(session)
        whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
        if "第一版" in latest:
            text = "第一版我建议先做任务列表、项目资料库、搜索和设置；确认后再开始生成。"
        elif "总结" in latest:
            text = "现在理解是小团队本地任务和项目资料管理工具；确认后再开始生成。"
        else:
            text = "我把这条并入当前项目范围，先继续收敛，不直接开工。"
        return text, whiteboard, "continue_chat"

    monkeypatch.setattr(bridge, "apply_backend_dialogue_tick", fake_analysis)
    monkeypatch.setattr(bridge, "customer_service_reply", fake_customer_reply)
    monkeypatch.setattr(bridge, "provider_user_message", lambda **kwargs: "当前按同一项目上下文处理；没有证据前不会说完成。")
    monkeypatch.setattr(bridge, "local_project_generation_available", lambda: False)


def test_ambiguous_requirement_does_not_start_until_explicit_confirmation(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        client = FakeTelegramClient()
        starts: list[str] = []
        _patch_dialogue(monkeypatch)

        def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
            starts.append(reason)
            session = bridge.load_session(session_dir_arg, chat_id)
            session["generation"] = {"status": "running", "driver": "controlled_start_test"}
            bridge.update_active_run_status(session, "running", driver="controlled_start_test")
            bridge.save_session(session_dir_arg, session)

        monkeypatch.setattr(bridge, "start_agent_generation", fake_start)

        messages = [
            "我想做一个工具",
            "做给小团队用的",
            "最好是本地运行",
            "能管理任务和项目资料",
            "第一版你觉得要做什么",
            "总结一下你理解的需求",
        ]
        for text in messages:
            bridge.handle_text(client, "start-a", text, session_dir, log_dir, "gpt-test", 60)
            assert starts == []

        bridge.handle_text(client, "start-a", "可以，就按这个开始做", session_dir, log_dir, "gpt-test", 60)
        assert len(starts) == 1

        bridge.handle_text(client, "start-a", "还在做吗", session_dir, log_dir, "gpt-test", 60)
        assert len(starts) == 1


def test_delivered_revision_requests_do_not_start_new_generation(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        client = FakeTelegramClient()
        _patch_dialogue(monkeypatch)
        starts: list[str] = []
        monkeypatch.setattr(bridge, "start_agent_generation", lambda *args, **kwargs: starts.append(str(kwargs.get("reason", ""))))

        session = bridge.default_session("start-b")
        session["whiteboard"]["project_summary"] = "本地任务管理系统"
        session["generation"] = {"status": "delivered", "driver": "controlled_delivery", "package_path": "final_project_bundle.zip"}
        session["active_run"] = {"id": "run-start-b", "status": "delivered", "package_path": "final_project_bundle.zip"}
        bridge.save_session(session_dir, session)

        bridge.handle_text(client, "start-b", "为什么还没有截图", session_dir, log_dir, "gpt-test", 60)
        bridge.handle_text(client, "start-b", "截图角度不够，补一个首页和设置页", session_dir, log_dir, "gpt-test", 60)
        bridge.handle_text(client, "start-b", "总结一下下一版要改什么", session_dir, log_dir, "gpt-test", 60)

        saved = bridge.load_session(session_dir, "start-b")
        assert starts == []
        assert saved["active_run"]["id"] == "run-start-b"
        assert saved["generation"]["status"] in {"delivered", "revision_requested", "next_revision_waiting_confirmation"}
        assert "截图角度不够" in "\n".join(saved["whiteboard"].get("change_requests", []))


def test_running_model_backend_question_explains_two_layers_without_restart(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        log_dir = pathlib.Path(temp_dir) / "logs"
        client = FakeTelegramClient()
        _patch_dialogue(monkeypatch)
        starts: list[str] = []

        def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
            starts.append(reason)
            session = bridge.load_session(session_dir_arg, chat_id)
            session["generation"] = {"status": "running", "driver": "controlled_start_test", "effective_generation_mode": "api"}
            bridge.update_active_run_status(session, "running", driver="controlled_start_test")
            bridge.save_session(session_dir_arg, session)

        monkeypatch.setattr(bridge, "start_agent_generation", fake_start)

        bridge.handle_text(client, "model-c", "我想做一个本地 AI 文档助手，可以导入文档、检索、总结，还要有界面", session_dir, log_dir, "gpt-test", 60)
        bridge.handle_text(client, "model-c", "走本地模型 + 开始做吧", session_dir, log_dir, "gpt-test", 60)
        assert starts
        starts_before = len(starts)

        bridge.handle_text(client, "model-c", "你是用 API 还是本地模型生成？", session_dir, log_dir, "gpt-test", 60)

        saved = bridge.load_session(session_dir, "model-c")
        reply = client.messages[-1][1]
        assert len(starts) == starts_before
        assert "CGKN" in reply
        assert "生成出来的项目" in reply
        assert "本地模型" in reply
        assert saved["whiteboard"]["target_project_architecture"]["model_mode"] == "local_model"
        assert saved["whiteboard"]["cgkn_execution"]["generation_backend"] == "api"

        bridge.handle_text(client, "model-c", "那项目里面要怎么处理没有本地模型文件的情况？", session_dir, log_dir, "gpt-test", 60)
        no_model_reply = client.messages[-1][1]
        assert "配置入口" in no_model_reply
        assert "mock" in no_model_reply
        assert "不能宣称真实推理通过" in no_model_reply

        bridge.handle_text(client, "model-c", "总结一下现在做到哪了", session_dir, log_dir, "gpt-test", 60)
        summary_reply = client.messages[-1][1]
        assert "项目内部" in summary_reply
        assert "本地模型" in summary_reply
        assert "CGKN" in summary_reply
