from __future__ import annotations

from typing import Any


class ProductStudioReplyComposer:
    def timeout_or_blocked_reply(self, failure_result: dict[str, Any]) -> str:
        reason = str(failure_result.get("reason", "blocked"))
        last_phase = str(failure_result.get("last_known_phase", "") or "unknown")
        missing = failure_result.get("missing_artifacts", [])
        if not isinstance(missing, list):
            missing = []
        missing_text = "、".join(str(item) for item in missing[:8]) or "未记录"
        retry = "可以重试，并复用 product_studio_run.json、customer_intent.raw_user_message、output_contract 和 frozen_project_type。"
        if reason == "project_type_mismatch":
            lead = "虚拟项目组已阻止交付：项目方向偏题，生成内容与冻结项目类型不一致。"
        elif "timeout" in reason:
            lead = "虚拟项目组已暂停交付：后台生成超过本轮等待时间，不能把未验证产物说成完成。"
        else:
            lead = "虚拟项目组已暂停交付：生成链被阻断，当前不能进入交付。"
        return (
            f"{lead}\n"
            f"阻断原因: {reason}\n"
            f"最后阶段: {last_phase}\n"
            f"缺失 artifact: {missing_text}\n"
            f"{retry}"
        )


def compose_timeout_or_blocked_reply(failure_result: dict[str, Any]) -> str:
    return ProductStudioReplyComposer().timeout_or_blocked_reply(failure_result)
