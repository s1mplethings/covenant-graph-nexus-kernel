from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

import pytest

pytestmark = pytest.mark.codex

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for value in (ROOT, SCRIPTS):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import scripts.codex_capability_supervisor as supervisor
import scripts.codex_design_supervision as design
import scripts.codex_conversation as bridge


def _design_session(text: str) -> dict:
    whiteboard = design.apply_design_intent(
        {"project_summary": "做一个辅助考研项目", "acceptance_criteria": []},
        text,
    )
    return {
        "conversation_id": "design-chat",
        "messages": [{"role": "user", "text": text}],
        "whiteboard": whiteboard,
        "memory_events": [],
        "whiteboard_versions": [],
    }


def test_interface_request_freezes_codex_and_visual_acceptance() -> None:
    session = _design_session("为什么没有 GUI？我要从 Codex 对话进入并重新设计项目界面")
    state = session["whiteboard"]["product_design"]

    assert state["required"] is True
    assert state["workflow_state"] == "awaiting_codex_brief"
    assert state["interaction_surfaces"] == ["codex_conversation"]
    acceptance = "\n".join(session["whiteboard"]["acceptance_criteria"])
    assert "一个明确功能" in acceptance
    assert "Codex 对话" in acceptance
    assert "明暗主题" in acceptance
    assert session["whiteboard"]["ready_to_generate"] is False


def test_media_only_short_request_does_not_gain_gui_scope() -> None:
    intent = design.design_intent_from_text("有生成测试图片视频吗？")
    whiteboard = design.apply_design_intent({"project_summary": "图片测试"}, "有生成测试图片视频吗？")

    assert intent["required"] is False
    assert "product_design" not in whiteboard
    assert design.design_intent_from_text("build a short JSON function")["required"] is False


def test_provider_design_scope_does_not_block_explicit_start() -> None:
    session = _design_session("给考研助手增加项目界面")
    allowed, reason = bridge.should_auto_start_generation(
        session,
        {"start_allowed_with_assumptions": True, "project_summary": "考研助手"},
        "直接开始生成",
    )

    assert allowed is True
    assert reason == "explicit_start_requested"


def test_production_bridge_records_provider_design_scope_without_codex() -> None:
    session = _design_session("给考研助手增加项目界面")
    session["generation"] = {"status": "idle"}
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        result = bridge.record_provider_design_scope(
            mock.Mock(),
            "design-chat",
            root / "sessions",
            root / "logs",
            session,
        )

        assert result["status"] == "provider_planner_ready"
        assert session["whiteboard"]["product_design"]["workflow_state"] == "provider_planner_pending"
        assert session["whiteboard"]["product_design"]["codex_used"] is False
        assert session["whiteboard"]["product_design"]["user_confirmation_required"] is False


def test_prepare_and_validate_bounded_design_handoff() -> None:
    session = _design_session("从 Codex 对话进入，给考研助手做 GUI")
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
    session = _design_session("从 Codex 对话进入，给考研助手做 GUI")
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
                        "summary": "以 Codex 对话处理决策，以生成项目界面承载连续浏览和编辑。",
                        "diagnosis": ["此前把业务叶子最小化误当成产品界面最小化。"],
                        "provider_guidance": ["实现项目首页、单功能操作页和统一动作契约。"],
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
