from __future__ import annotations

from typing import Any

try:
    import public_narration
except ModuleNotFoundError:  # pragma: no cover - direct package import fallback
    from scripts import public_narration


class ProductStudioReplyComposer:
    def timeout_or_blocked_reply(self, failure_result: dict[str, Any]) -> str:
        reason = str(failure_result.get("reason", "blocked"))
        last_phase = str(failure_result.get("last_known_phase", "") or "unknown")
        missing = failure_result.get("missing_artifacts", [])
        if not isinstance(missing, list):
            missing = []
        missing_text = "、".join(str(item) for item in missing[:8]) or "未记录"
        retry = "你可以继续补充要求，我会复用已记录的项目方向，从同一上下文继续修复。"
        if reason == "project_type_mismatch":
            lead = "暂时不能交付：项目方向出现偏差，当前产物和已整理的目标不一致。"
        elif "timeout" in reason:
            lead = "暂时不能交付：这一轮等待时间已到，未验证产物不能标成完成。"
        else:
            lead = "暂时不能交付：这轮实现被阻断，当前不能进入交付。"
        return public_narration.redact_internal_terms(
            f"{lead}\n"
            f"阻断原因: {reason}\n"
            f"最后进展: {last_phase}\n"
            f"缺失材料: {missing_text}\n"
            f"{retry}"
        )


def compose_timeout_or_blocked_reply(failure_result: dict[str, Any]) -> str:
    return ProductStudioReplyComposer().timeout_or_blocked_reply(failure_result)
