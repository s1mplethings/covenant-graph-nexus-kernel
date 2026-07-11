from __future__ import annotations

from typing import Any

try:
    import public_narration
    import frontdesk_team_lead_agent
except ModuleNotFoundError:  # pragma: no cover - direct package import fallback
    from scripts import public_narration
    from scripts import frontdesk_team_lead_agent


class ProductStudioReplyComposer:
    def timeout_or_blocked_reply(self, failure_result: dict[str, Any]) -> str:
        reason = str(failure_result.get("reason", "blocked"))
        last_phase = str(failure_result.get("last_known_phase", "") or "unknown")
        missing = failure_result.get("missing_artifacts", [])
        if not isinstance(missing, list):
            missing = []
        visible_reason = "这一轮等待时间已到，未验证的结果不能标成完成。" if "timeout" in reason else "当前结果和目标或证据要求还没有对齐。"
        context = frontdesk_team_lead_agent.build_context(
            latest_user_message="",
            conversation_history_summary="",
            whiteboard={"known_limits": [visible_reason, f"最近停在：{last_phase}"]},
            active_run={},
            generation_status={"status": "rework_blocked", "user_visible_cause": visible_reason},
            delivery_evidence={"delivery_ready": False, "missing": missing, "refs": {}},
            known_limits=[visible_reason, f"最近停在：{last_phase}"],
            customer_agent_policy="",
            draft_reply=visible_reason,
            event="generation_failed",
        )
        reply = frontdesk_team_lead_agent.compose_reply(context)["reply"]
        return public_narration.redact_internal_terms(reply)


def compose_timeout_or_blocked_reply(failure_result: dict[str, Any]) -> str:
    return ProductStudioReplyComposer().timeout_or_blocked_reply(failure_result)
