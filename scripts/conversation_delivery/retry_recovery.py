from __future__ import annotations

from typing import Any


def recovery_options(error: dict[str, Any]) -> dict[str, Any]:
    reason = str(error.get("reason") or error.get("status") or "").lower()
    if "quota" in reason:
        return {
            "status": "WAITING_FOR_PROVIDER_QUOTA",
            "message": "当前模型额度不足，请更换 provider 或稍后继续。",
            "can_retry": True,
            "can_continue": True,
            "can_cancel": True,
            "next_action": "switch_provider_or_retry_later",
        }
    if "transport" in reason or "timeout" in reason or "rate" in reason:
        return {
            "status": "FAILED_WITH_RECOVERY_OPTIONS",
            "message": "模型连接不稳定，可以重试或稍后继续。",
            "can_retry": True,
            "can_continue": True,
            "can_cancel": True,
            "next_action": "retry_generation",
        }
    return {
        "status": "FAILED_WITH_RECOVERY_OPTIONS",
        "message": "本次发送没有完成，可重试或取消。",
        "can_retry": True,
        "can_continue": False,
        "can_cancel": True,
        "next_action": "retry_delivery",
    }
