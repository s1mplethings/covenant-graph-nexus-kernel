from __future__ import annotations

import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.backend_dialogue_loop as dialogue
import scripts.telegram_live_bridge as bridge

pytestmark = [pytest.mark.telegram]


def _analysis_for(text: str, session: dict | None = None) -> tuple[dict, dict]:
    session = session or {"whiteboard": {}, "messages": [{"role": "user", "text": text}]}
    return session, dialogue.summarize_locally(session, text, reason="new_project_request")


def assert_auto_starts(text: str) -> dict:
    session, analysis = _analysis_for(text)
    allowed, reason = bridge.should_auto_start_generation(session, analysis, text)
    assert (allowed, reason) == (True, "actionable_project_request")
    return analysis


def test_image_generation_project_can_auto_start() -> None:
    analysis = assert_auto_starts("做一个本地可运行的素材生成工具，可以生成图片，有界面和自动化流程")

    assert "内容/素材生成" in analysis["required_capabilities"]
    assert "界面预览" in analysis["required_capabilities"]
    assert analysis["acceptance_criteria"]


def test_video_processing_project_can_auto_start() -> None:
    analysis = assert_auto_starts("做一个本地视频整理助手，可以导入视频，自动截取片段，导出结果，有界面")

    assert "视频或媒体处理" in analysis["required_capabilities"]
    assert "导出与报告" in analysis["required_capabilities"]


def test_api_automation_project_can_auto_start() -> None:
    analysis = assert_auto_starts("做一个本地自动化客服后台，可以接 API，整理用户需求，生成结果报告")

    assert "外部 API 对接" in analysis["required_capabilities"]
    assert "自动化流程" in analysis["required_capabilities"]


def test_vague_request_blocks() -> None:
    text = "帮我做个东西"
    session, analysis = _analysis_for(text)

    allowed, reason = bridge.should_auto_start_generation(session, analysis, text)

    assert allowed is False
    assert reason == "unclear_project_request"


def test_missing_model_config_does_not_block_scaffold_but_records_limits() -> None:
    text = "做一个本地模型图片生成工具"
    session, analysis = _analysis_for(text)

    allowed, reason = bridge.should_auto_start_generation(session, analysis, text)

    assert (allowed, reason) == (True, "actionable_project_request")
    joined = "；".join(analysis["assumptions"] + analysis["acceptance_criteria"] + analysis["known_limits"] + analysis["missing_config"])
    assert "模型" in joined
    assert "不能算真实" in joined or "不能算完整" in joined or "不宣称完整" in joined


def test_answered_soft_questions_are_resolved_generically() -> None:
    session = {
        "whiteboard": {
            "project_summary": "做一个本地素材生成工具，可以生成图片和报告",
            "soft_questions": ["交付重点是界面、文件导出、还是自动化流程？", "第一版运行方式是什么？"],
        },
        "messages": [],
    }

    analysis = dialogue.summarize_locally(session, "界面 + 自动化流程 + 文件导出，本地运行", reason="project_update")

    assert "交付重点是界面、文件导出、还是自动化流程？" not in analysis["soft_questions"]
    assert "第一版运行方式是什么？" not in analysis["soft_questions"]
    assert bridge.should_auto_start_generation(session, analysis, "界面 + 自动化流程 + 文件导出，本地运行")[0] is True


def test_actionable_waiting_and_grounded_text_do_not_use_blocking_copy() -> None:
    text = "做一个本地自动化素材处理工具，可以导入文件、生成预览、导出报告"
    session, analysis = _analysis_for(text)
    session["whiteboard"]["project_summary"] = text
    session["messages"].append({"role": "user", "text": text})

    waiting = bridge.build_intake_waiting_text(analysis)
    grounded = bridge.grounded_current_goal_reply(session)
    combined = waiting + "\n" + grounded

    assert "不会马上开工" not in combined
    assert "交付重点是界面、文件导出、还是自动化流程" not in combined


def test_public_delivery_judgment_blocks_requested_asset_gaps() -> None:
    session = bridge.default_session("chat-generic-gate")
    session["whiteboard"]["project_summary"] = "做一个本地素材处理工具，需要界面截图、生成图片、视频预览、报告和项目包"
    session["whiteboard"]["delivery_requirements"] = ["界面截图", "生成图片", "视频预览", "报告", "项目包"]
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        (project / "main.py").write_text("print('tool')\n", encoding="utf-8")
        (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (project / "TEST_REPORT.md").write_text("commands_run:\n- python main.py\n", encoding="utf-8")
        (project / "DELIVERY_NOTES.md").write_text("delivery_status: PASS\n", encoding="utf-8")
        manifest = {
            "project_dir": str(project),
            "startup_command": "python main.py",
            "quality_evidence": {
                "test_report_found": True,
                "test_report_has_commands": True,
                "test_report_has_no_test_executed": False,
            },
        }

        gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")

    assert gate["delivery_allowed"] is False
    assert gate["verdict"] == "NEEDS_REWORK"
    assert gate["is_final"] is False
    assert gate["judgment_source"] == "canonical_evidence_gate"
    assert "production_candidate_provenance" in gate[
        "canonical_evidence_gate"
    ]["failures"]
    assert gate["required_repairs"]
