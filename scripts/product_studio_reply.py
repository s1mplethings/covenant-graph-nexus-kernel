from __future__ import annotations

from typing import Any

try:
    import team_narration
except ModuleNotFoundError:  # pragma: no cover - direct package import fallback
    from scripts import team_narration


class ProductStudioReplyComposer:
    def timeout_or_blocked_reply(self, failure_result: dict[str, Any]) -> str:
        reason = str(failure_result.get("reason", "blocked"))
        last_phase = str(failure_result.get("last_known_phase", "") or "unknown")
        missing = failure_result.get("missing_artifacts", [])
        if not isinstance(missing, list):
            missing = []
        missing_text = "、".join(str(item) for item in missing[:8]) or "未记录"
        retry = "你可以继续补充要求，林然会复用已记录的项目方向，许楠和陈序从同一上下文继续修复。"
        if reason == "project_type_mismatch":
            lead = "乔安暂时阻止交付：项目方向出现偏差，当前产物和林然整理的目标不一致。"
        elif "timeout" in reason:
            lead = "乔安暂时暂停交付：这一轮等待时间已到，陈序还不能把未验证产物标成完成。"
        else:
            lead = "乔安暂时暂停交付：许楠这轮实现被阻断，当前不能进入交付。"
        return team_narration.redact_internal_terms(
            f"{lead}\n"
            f"阻断原因: {reason}\n"
            f"最后进展: {last_phase}\n"
            f"缺失材料: {missing_text}\n"
            f"{retry}"
        )


def compose_timeout_or_blocked_reply(failure_result: dict[str, Any]) -> str:
    return ProductStudioReplyComposer().timeout_or_blocked_reply(failure_result)
