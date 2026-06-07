from __future__ import annotations

from typing import Any


TEAM_ROSTER = {
    "product": {"name": "林然", "title": "产品经理"},
    "architect": {"name": "周衡", "title": "架构师"},
    "engineer": {"name": "许楠", "title": "工程师"},
    "ux": {"name": "沈镜", "title": "体验设计"},
    "qa": {"name": "陈序", "title": "测试工程师"},
    "delivery": {"name": "乔安", "title": "交付负责人"},
}


INTERNAL_TERM_REPLACEMENTS = (
    ("pipeline_manifest", "项目执行计划"),
    ("dynamic_pipeline_runner", "后台执行流程"),
    ("local_packager", "交付整理"),
    ("delivery_manifest", "交付清单"),
    ("agent_session", "团队工作记录"),
    ("backend_dialogue_loop", "需求分析"),
    ("user_evidence_checkpoint", "用户证据确认"),
    ("waiting_user_review", "等待用户确认"),
    ("quality_evidence", "质量证据"),
    ("local_packager", "交付整理"),
    ("whiteboard", "项目白板"),
    ("truth ledger", "交付记录"),
    ("truth_ledger", "交付记录"),
    ("JSONL", "记录文件"),
    ("jsonl", "记录文件"),
    ("runner", "执行流程"),
    ("manifest", "清单"),
    ("pipeline", "流程"),
    ("scripts/", ""),
    ("script", "工具"),
)


def redact_internal_terms(text: str) -> str:
    cleaned = str(text or "")
    for old, new in INTERNAL_TERM_REPLACEMENTS:
        cleaned = cleaned.replace(old, new)
    return cleaned


def _questions_text(facts: dict[str, Any]) -> str:
    questions = facts.get("questions") or facts.get("critical_questions") or facts.get("blocking_questions") or []
    if not isinstance(questions, list):
        return ""
    visible = [str(item).strip() for item in questions if str(item).strip()]
    if not visible:
        return ""
    return "\n需要你确认：\n" + "\n".join(f"{index}. {item}" for index, item in enumerate(visible[:3], 1))


def team_say(event: str, facts: dict[str, Any] | None = None) -> str:
    facts = facts or {}
    if event == "intake_waiting":
        text = (
            "林然已经把需求整理成第一版方向。周衡认为还有几个关键点会影响技术路线，所以团队先不急着开工。"
            f"{_questions_text(facts)}\n"
            "你可以补充这些信息；如果想先做框架版，也可以说“按默认假设开始”，团队会按框架版先推进。"
        )
    elif event == "generation_started":
        text = (
            "收到，我让林然和周衡按当前假设立项。许楠开始做可运行版本，陈序会准备测试代码和测试记录。"
            "如果需要你判断截图、视频或预览，我会先发给你确认，再让乔安打包。"
        )
    elif event == "evidence_checkpoint":
        text = (
            "陈序已经整理了测试代码和测试命令，沈镜也把可视化/视频/预览证据列出来了。你可以先判断效果。\n"
            "回复：\n"
            "- 继续/打包：让乔安最终复核并交付\n"
            "- 修改：告诉许楠要改哪里\n"
            "- 重新测试：让陈序补跑测试"
        )
    elif event == "delivery_ready":
        text = "乔安完成了交付复核。下面是项目包、测试情况、预览证据和已知限制。"
    elif event == "generation_warning":
        warning = str(facts.get("warning") or "").strip()
        text = warning or "陈序提醒：这轮缺少真实输入，所以只能算框架版或样例级验证，不能视为真实业务验证通过。"
    elif event == "review_continue":
        text = "收到，我让乔安进入最终复核和打包。陈序的测试记录和沈镜的预览证据会一起放进交付说明。"
    elif event == "review_revision":
        text = "收到，我把这条反馈交给许楠和陈序处理。许楠会先改实现，陈序会重新整理测试记录，之后我再把新的预览/测试证据发给你判断。"
    else:
        text = str(facts.get("message") or "").strip() or "林然已记录这条消息，团队会按当前项目上下文继续处理。"
    return redact_internal_terms(text)
