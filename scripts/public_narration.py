from __future__ import annotations

from typing import Any


INTERNAL_TERM_REPLACEMENTS = {
    "pipeline_manifest": "项目执行计划",
    "dynamic_pipeline_runner": "后台执行流程",
    "local_packager": "交付整理",
    "delivery_manifest": "交付清单",
    "agent_session": "工作记录",
    "backend_dialogue_loop": "需求分析",
    "user_evidence_checkpoint": "用户证据确认",
    "waiting_user_review": "等待用户确认",
    "quality_evidence": "质量证据",
    "whiteboard": "项目记录",
    "truth ledger": "交付记录",
    "truth_ledger": "交付记录",
    "JSONL": "记录文件",
    "jsonl": "记录文件",
    "runner": "执行流程",
    "manifest": "清单",
    "pipeline": "流程",
    "scripts/": "",
    "script": "工具",
    "internal module": "内部实现",
    "stage id": "步骤标识",
}


def redact_internal_terms(text: str) -> str:
    cleaned = str(text or "")
    for old, new in INTERNAL_TERM_REPLACEMENTS.items():
        cleaned = cleaned.replace(old, new)
    return cleaned


def _question_lines(facts: dict[str, Any]) -> str:
    questions = facts.get("questions") or facts.get("critical_questions") or facts.get("blocking_questions") or []
    if not isinstance(questions, list):
        return ""
    visible = [str(item).strip() for item in questions if str(item).strip()]
    if not visible:
        return ""
    return "\n需要你确认：\n" + "\n".join(f"{index}. {item}" for index, item in enumerate(visible[:3], 1))


def public_event_text(event: str, facts: dict[str, Any] | None = None) -> str:
    facts = facts or {}
    if event == "intake_waiting":
        text = (
            "我先把需求整理成第一版方向，但现在有几个点会直接影响实现质量，所以不会马上开工。"
            f"{_question_lines(facts)}\n\n"
            "你可以补充这些信息；如果想先做框架版，也可以回复“开始生成”或“按默认假设开始”，我会把缺少真实验证写进限制。"
        )
    elif event == "generation_started":
        text = (
            "收到，我会按当前假设开始做第一版。接下来会依次完成：项目范围、技术方案、可运行版本、"
            "测试代码、测试记录和预览证据。如果中间需要你判断效果，我会先把测试命令、截图或视频发给你。"
        )
    elif event == "evidence_checkpoint":
        text = (
            "中间测试和预览证据已经整理好。你可以先看这些内容再决定是否继续。\n\n"
            "回复“继续/打包”进入最终交付；如果要改，直接说改哪里；如果要重新测试，也可以直接说明。"
        )
    elif event == "delivery_ready":
        text = "最终交付已经整理好。下面是项目包、测试情况、预览证据、真实输入验证和已知限制。"
    elif event == "generation_warning":
        text = str(facts.get("warning") or "").strip() or "这轮缺少真实输入，所以只能算框架版或样例级验证，不能视为真实业务验证通过。"
    elif event == "review_continue":
        text = "收到，我会进入最终复核和打包。刚才的测试记录和预览证据会一起放进交付说明。"
    elif event == "review_revision":
        text = "收到，我会按这条反馈回到实现、测试和预览证据整理阶段，不会直接最终打包。"
    else:
        text = str(facts.get("message") or "").strip() or "这条消息已记录，我会按当前项目上下文继续处理。"
    return redact_internal_terms(text)
