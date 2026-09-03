from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import frontdesk_team_lead_agent as agent
from scripts import main_agent_manager
from scripts import codex_conversation as bridge


FORBIDDEN_PUBLIC_TERMS = (
    "provider",
    "pipeline",
    "manifest",
    "runner",
    "JSONL",
    "jsonl",
    "BLOCKED",
    "TLS",
    "SSL",
    "SSLError",
    "transport",
    "traceback",
    "exception",
)


def make_context(**overrides):
    base = {
        "latest_user_message": "你好",
        "conversation_history_summary": "",
        "whiteboard": {},
        "active_run": {},
        "generation_status": {"status": "idle"},
        "delivery_evidence": {"delivery_ready": False, "missing": [], "refs": {}},
        "known_limits": [],
        "customer_agent_policy": "像项目负责人沟通。",
        "draft_reply": "",
        "event": "",
    }
    base.update(overrides)
    return base


def assert_public_clean(text: str) -> None:
    for term in FORBIDDEN_PUBLIC_TERMS:
        assert term not in text
    assert "虚拟项目组" not in text
    assert "客服" not in text


def test_greeting_reply_is_contextual_and_structured() -> None:
    reply = agent.compose_reply(make_context(latest_user_message="你好", event="greeting"))

    assert reply["reply_intent"] == "greeting"
    assert reply["visible_status"] == "尚未开始"
    assert reply["next_user_options"]
    assert "我" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_status_query_only_reports_state_and_missing_evidence() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="还在做吗",
            event="status_requested",
            generation_status={"status": "running"},
            active_run={"status": "running"},
            delivery_evidence={"delivery_ready": False, "missing": ["package", "verify_report"], "refs": {}},
        )
    )

    assert reply["reply_intent"] == "status"
    assert "后台正在处理" in reply["reply"]
    assert not reply["reply"].startswith("当前状态：")
    assert "缺的证据" in reply["reply"]
    assert "重新" not in reply["reply"]
    assert all("生成" not in option for option in reply["next_user_options"])
    assert_public_clean(reply["reply"])


def test_status_summary_naturalizes_record_style_change_requests() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="总结一下现在做到哪了",
            event="status_requested",
            whiteboard={
                "project_summary": "本地项目生成系统",
                "change_requests": [
                    "用户纠正: 不是普通代码生成，我要像项目团队一样交付",
                    "补齐截图和测试证据",
                    "前台回复仍偏机械，需要更像项目负责人沟通",
                ],
            },
            generation_status={"status": "running"},
            delivery_evidence={"delivery_ready": False, "missing": ["screenshot", "verify_report"], "refs": {}},
        )
    )

    assert reply["reply_intent"] == "status"
    assert "用户纠正:" not in reply["reply"]
    assert "用户补充:" not in reply["reply"]
    assert "change_request:" not in reply["reply"]
    assert "你已经明确强调过" in reply["reply"]
    assert "真实截图和测试证据" in reply["reply"]
    assert "更像项目负责人" in reply["reply"]
    assert "还不能说完成" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_ambiguous_requirement_gets_project_lead_reply() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="做一个管理系统",
            whiteboard={"project_summary": "管理系统"},
        )
    )

    assert reply["reply_intent"] == "project_intake"
    assert "第一版" in reply["reply"]
    assert "验收" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_start_generation_reply_does_not_claim_human_team() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="开始生成",
            event="generation_started",
            whiteboard={"project_summary": "本地任务管理器"},
            generation_status={"status": "running"},
        )
    )

    assert reply["reply_intent"] == "start_generation"
    assert "项目生成流程" in reply["reply"]
    assert "员工" not in reply["reply"]
    assert "手工开发" not in reply["reply"]
    assert_public_clean(reply["reply"])


def test_local_model_start_phrase_is_start_generation_not_change_request() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="走本地模型 + 开始做吧",
            event="project_update_running",
            whiteboard={"project_summary": "本地项目生成系统"},
            generation_status={"status": "waiting_confirmation"},
        )
    )

    assert reply["reply_intent"] == "start_generation"
    assert "启动第一版" in reply["reply"]
    assert "修改要求" not in reply["reply"]
    assert_public_clean(reply["reply"])


def test_change_request_reply_is_recordable() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="加上导出 Excel，必须保留历史",
            event="project_update_running",
            generation_status={"status": "running"},
        )
    )

    assert reply["reply_intent"] == "change_request"
    assert "修改要求" not in reply["reply"]
    assert "沿用当前项目继续推进" in reply["reply"]
    assert "不另开无关目标" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_change_request_reply_uses_owner_judgment_not_record_template() -> None:
    first = agent.compose_reply(
        make_context(
            latest_user_message="那先补截图和测试",
            event="project_update_running",
            generation_status={"status": "running"},
        )
    )
    second = agent.compose_reply(
        make_context(
            latest_user_message="这块说话还是太机械",
            event="project_update_running",
            generation_status={"status": "running"},
            conversation_history_summary=f"assistant: {first['reply']}",
        )
    )

    assert first["reply_intent"] == "change_request"
    assert second["reply_intent"] == "change_request"
    assert first["reply"].startswith("对，下一步")
    assert "真实截图和测试结论" in first["reply"]
    assert "不能算完成" in first["reply"]
    assert second["reply"].startswith("明白，这不是小问题")
    assert "固定记录口吻" in second["reply"]
    assert "这条我记下了" not in second["reply"]
    assert "这条我会作为修改要求记录" not in first["reply"] + second["reply"]
    assert_public_clean(first["reply"])
    assert_public_clean(second["reply"])


def test_correction_reply_acknowledges_fix_first() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="不是 CRM，我要的是个人任务看板",
            whiteboard={"project_summary": "CRM"},
        )
    )

    assert reply["reply_intent"] == "correction"
    assert reply["reply"].startswith("收到，按你的说法修正")
    assert "个人任务看板" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_missing_evidence_reply_is_natural() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="好了没",
            event="generation_failed",
            generation_status={"status": "rework_blocked"},
            delivery_evidence={"delivery_ready": False, "missing": ["delivery_manifest", "screenshot"], "refs": {}},
        )
    )

    assert reply["reply_intent"] in {"status", "evidence_missing"}
    assert "不能" in reply["reply"] or "缺" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_missing_evidence_reply_keeps_only_main_gaps() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="怎么还不能交付",
            event="generation_failed",
            generation_status={"status": "rework_blocked"},
            delivery_evidence={"delivery_ready": False, "missing": ["package", "screenshot", "verify_report", "video", "delivery_manifest"], "refs": {}},
            known_limits=[
                "缺少真实模型、外部 API、媒体后端或数据集时，只能交付配置入口、适配层、测试框架和限制说明",
                "占位图、纯色图、降级预览或模拟结果不能算真实核心能力验收通过",
                "未配置：模型路径或本地/外部生成后端配置",
            ],
        )
    )

    assert "这轮还不能交付" in reply["reply"]
    assert "可运行项目文件、效果预览、测试结论" in reply["reply"]
    assert "演示视频" not in reply["reply"]
    assert "交付清单" not in reply["reply"]
    assert "占位图" not in reply["reply"]
    assert "验收标准" not in reply["reply"]
    assert_public_clean(reply["reply"])


def test_config_gap_reply_is_not_delivery_failure() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="开始生成",
            event="generation_failed",
            generation_status={"status": "waiting_confirmation"},
            delivery_evidence={"delivery_ready": False, "missing": [], "refs": {}},
            known_limits=["未配置：模型路径或本地/外部生成后端配置"],
        )
    )

    assert "还不该直接开做" in reply["reply"]
    assert "配置选择" in reply["reply"]
    assert "交付检查" not in reply["reply"]
    assert_public_clean(reply["reply"])


def test_public_reply_removes_structure_labels_and_raw_status_phrase() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="继续",
            draft_reply="判断：可以按当前目标推进。\n原因：资料已经够第一版。\n下一步：开始生成。当前状态是等待确认。",
        )
    )

    assert "判断：" not in reply["reply"]
    assert "原因：" not in reply["reply"]
    assert "下一步：" not in reply["reply"]
    assert "状态是" not in reply["reply"]
    assert "现在这边是等待确认" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_user_visible_failure_sanitizes_transport_terms() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="怎么失败了",
            event="generation_failed",
            generation_status={"status": "rework_blocked", "error": "provider TLS failed with SSLError traceback"},
            delivery_evidence={"delivery_ready": False, "missing": ["package"], "refs": {}},
        )
    )

    assert "生成服务暂时连接失败" in reply["reply"]
    assert "当前不能继续交付" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_delivery_complete_reply_lists_available_evidence() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="交付了吗",
            event="delivery_ready",
            generation_status={"status": "ready"},
            delivery_evidence={"delivery_ready": True, "missing": [], "refs": {"package": "x.zip", "screenshot": "x.png"}},
        )
    )

    assert reply["reply_intent"] == "delivery_complete"
    assert "交付已经整理好" in reply["reply"]
    assert "可运行项目文件" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_delivery_send_failed_is_not_presented_as_complete() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="交付了吗",
            event="delivery_send_failed",
            generation_status={"status": "delivery_send_failed"},
            delivery_evidence={"delivery_ready": True, "missing": [], "refs": {"package": "x.zip", "screenshot": "x.png"}},
            known_limits=["Codex conversation 附件没有全部发送成功"],
        )
    )

    assert reply["visible_status"] == "需要补证或修复"
    assert "最终交付已经整理好" not in reply["reply"]
    assert "完成" not in reply["reply"] or "不能" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_generic_change_request_reply_is_not_record_template() -> None:
    reply = agent.compose_reply(
        make_context(
            latest_user_message="后续要加一个历史记录页面",
            event="project_update_running",
            generation_status={"status": "running"},
        )
    )

    assert reply["reply_intent"] == "change_request"
    assert "这个修改要求会调整当前优先级" not in reply["reply"]
    assert "我会把它并入当前项目上下文" not in reply["reply"]
    assert "这会改变这一版的优先级" in reply["reply"]
    assert_public_clean(reply["reply"])


def test_codex_send_customer_reply_uses_team_lead_metadata() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def send_message(self, conversation_id, text):
            self.messages.append((str(conversation_id), text))
            return True

    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = pathlib.Path(temp_dir) / "sessions"
        session = bridge.default_session("chat")
        bridge.send_customer_reply(
            FakeClient(),
            "chat",
            session_dir,
            session,
            event="status_requested",
            facts={"generation": {"status": "running"}, "evidence_state": {"delivery_ready": False, "missing": ["package"], "refs": {}}},
            direct_text="provider pipeline BLOCKED",
        )
        saved = bridge.load_session(session_dir, "chat")

    assert saved["last_team_lead_reply"]["reply_intent"] == "status"
    assert saved["last_team_lead_reply"]["visible_status"] == "后台正在处理"
    assert_public_clean(saved["messages"][-1]["text"])


def test_local_studio_result_contains_team_lead_reply_and_correction_memory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", str(tmp_path / "conversations"))
    manager = main_agent_manager.MainAgentManager()

    result = manager.handle_user_turn("lead-local", "不是 CRM，我要的是个人任务看板", source="local_cli")

    assert result["reply_intent"] == "correction"
    assert result["user_visible_reply"].startswith("收到，按你的说法修正")
    assert "next_user_options" in result
    conversation = main_agent_manager.local_conversation_manager.load_conversation("lead-local")
    assert "用户纠正" in "\n".join(conversation["whiteboard"]["change_requests"])
    assert_public_clean(result["user_visible_reply"])
