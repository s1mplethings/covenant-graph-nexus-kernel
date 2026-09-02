from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for value in (ROOT, SCRIPTS):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import scripts.codex_capability_supervisor as supervisor
import scripts.telegram_design_supervision as design
import scripts.telegram_live_bridge as bridge


def _design_session(text: str) -> dict:
    whiteboard = design.apply_design_intent(
        {"project_summary": "做一个辅助考研项目", "acceptance_criteria": []},
        text,
    )
    return {
        "chat_id": "design-chat",
        "messages": [{"role": "user", "text": text}],
        "whiteboard": whiteboard,
        "memory_events": [],
        "whiteboard_versions": [],
    }


def test_interface_request_freezes_bot_mini_app_and_visual_acceptance() -> None:
    session = _design_session("为什么没有 GUI？我要从 Telegram 对话进入并用 Mini App 操作，重新设计")
    state = session["whiteboard"]["product_design"]

    assert state["required"] is True
    assert state["workflow_state"] == "awaiting_codex_brief"
    assert state["interaction_surfaces"] == ["telegram_bot", "telegram_mini_app"]
    acceptance = "\n".join(session["whiteboard"]["acceptance_criteria"])
    assert "一个明确功能" in acceptance
    assert "initData" in acceptance
    assert "明暗主题" in acceptance
    assert session["whiteboard"]["ready_to_generate"] is False


def test_media_only_short_request_does_not_gain_gui_scope() -> None:
    intent = design.design_intent_from_text("有生成测试图片视频吗？")
    whiteboard = design.apply_design_intent({"project_summary": "图片测试"}, "有生成测试图片视频吗？")

    assert intent["required"] is False
    assert "product_design" not in whiteboard
    assert design.design_intent_from_text("build a short JSON function")["required"] is False


def test_pending_design_blocks_even_explicit_start() -> None:
    session = _design_session("给考研助手增加 Telegram Mini App 界面")
    allowed, reason = bridge.should_auto_start_generation(
        session,
        {"start_allowed_with_assumptions": True, "project_summary": "考研助手"},
        "直接开始生成",
    )

    assert allowed is False
    assert reason == "product_design_confirmation_pending"


def test_every_generation_entry_obeys_pending_design_checkpoint() -> None:
    session = _design_session("给考研助手增加 Telegram Mini App 界面")
    session["generation"] = {"status": "idle"}
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        with mock.patch.object(bridge, "send_customer_reply") as send_reply, mock.patch.object(bridge, "save_session"):
            started = bridge.start_generation_from_income(
                mock.Mock(),
                "design-chat",
                root / "sessions",
                root / "logs",
                "test-model",
                30,
                session,
                reason="test",
                generation_mode="api",
            )

        assert started is False
        assert session["generation"]["status"] == "waiting_confirmation"
        assert session["generation"]["start_wait_reason"] == "product_design_confirmation_pending"
        send_reply.assert_called_once()


def test_prepare_and_validate_bounded_design_handoff() -> None:
    session = _design_session("从 Telegram 对话进入 Mini App，给考研助手做 GUI")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        agent_session = root / "design-chat" / "agent_session.jsonl"
        prepared = design.prepare_design_escalation(root, "design-chat", session, agent_session)

        request = prepared["request"]
        assert supervisor.validate_escalation_request(request) == []
        assert request["authority"] == {
            "advisory_only": True,
            "formal_evidence_authorized": False,
            "candidate_write_authorized": False,
            "package_authorized": False,
            "delivery_authorized": False,
        }
        assert pathlib.Path(prepared["request_path"]).is_file()
        event = json.loads(agent_session.read_text(encoding="utf-8").splitlines()[0])
        assert event["kind"] == "codex_capability_escalation_requested"
        assert event["advisory_only"] is True


def test_read_only_codex_draft_is_sealed_then_requires_user_confirmation() -> None:
    session = _design_session("从 Telegram 对话进入 Mini App，给考研助手做 GUI")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        agent_session = root / "design-chat" / "agent_session.jsonl"
        prepared = design.prepare_design_escalation(root, "design-chat", session, agent_session)

        def fake_run(argv, **kwargs):
            output_path = pathlib.Path(argv[argv.index("--output-last-message") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "workflow_state": "ready",
                        "summary": "以对话处理低频决策，以 Mini App 承载连续浏览和编辑。",
                        "diagnosis": ["此前把业务叶子最小化误当成产品界面最小化。"],
                        "provider_guidance": ["实现 Bot 入口、Mini App 首页、单功能操作页和统一动作契约。"],
                        "repair_targets": [],
                        "acceptance_checks": ["在 390px 宽度完成主要流程并提供明暗主题截图。"],
                        "context_requests": [],
                        "tool_evidence_requests": ["运行浏览器交互并录制关键流程视频。"],
                        "known_limits": ["设计简报不代表实现或交付通过。"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with mock.patch.object(design.subprocess, "run", side_effect=fake_run):
            result = design.run_codex_design_supervision(
                pathlib.Path(prepared["request_path"]),
                agent_session,
                codex_command="codex-test",
                timeout=60,
            )

        brief = result["brief"]
        assert supervisor.validate_capability_brief(brief) == []
        assert brief["authority"]["formal_evidence_status"] == "NOT_EVALUATED"
        assert brief["authority"]["candidate_write_authorized"] is False
        projected = design.apply_design_brief(session["whiteboard"], result)
        assert projected["product_design"]["workflow_state"] == "awaiting_user_confirmation"
        assert design.design_supervision_pending(projected) is True

        approved = design.apply_design_intent(projected, "设计确认，开始生成")
        assert approved["product_design"]["workflow_state"] == "approved"
        assert design.design_supervision_pending(approved) is False


@pytest.mark.telegram
def test_telegram_web_app_button_requires_https_and_web_app_data_is_normalized() -> None:
    client = bridge.TelegramClient("test-token", timeout=5)
    captured: list[tuple[str, dict]] = []
    client.call = lambda method, payload=None: captured.append((method, payload or {})) or {"ok": True}

    assert client.send_message("chat", "打开", web_app_url="http://unsafe.example/app") is True
    assert "reply_markup" not in captured[-1][1]
    assert client.send_message("chat", "打开", web_app_url="https://example.com/app") is True
    markup = json.loads(captured[-1][1]["reply_markup"])
    assert markup["inline_keyboard"][0][0]["web_app"]["url"] == "https://example.com/app"

    message = design.web_app_user_text({"data": json.dumps({"action": "build_weekly_plan", "payload": {"hours": 20}})})
    assert "build_weekly_plan" in message
    assert '"hours": 20' in message
