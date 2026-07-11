#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
from typing import Any


PUBLIC_STATUSES = {
    "QUEUED",
    "PROVIDER_CHECKING",
    "GENERATING",
    "BUILDING",
    "REPAIRING_TESTS",
    "CAPTURING_SCREENSHOT",
    "CAPTURING_VIDEO",
    "READY_FOR_REVIEW",
    "PACKAGING_FINAL",
    "FINAL_READY",
    "WAITING_FOR_PROVIDER_QUOTA",
    "NEEDS_USER_DECISION",
    "FAILED_WITH_RECOVERY_OPTIONS",
}
FORBIDDEN_TERMS = ("FACT_BLOCKED", "gate", "traceback", "PASS_FINAL", "BLOCKED")


MESSAGES = {
    "QUEUED": "已收到需求，正在排队准备生成。",
    "PROVIDER_CHECKING": "正在检查模型服务和可用额度。",
    "GENERATING": "正在生成项目文件。",
    "BUILDING": "正在安装依赖并构建项目。",
    "REPAIRING_TESTS": "测试未完全通过，正在修复可恢复的问题。",
    "CAPTURING_SCREENSHOT": "项目已可运行，正在生成界面截图。",
    "CAPTURING_VIDEO": "截图已完成，正在录制演示视频。",
    "READY_FOR_REVIEW": "候选项目已生成，测试已通过，截图和视频已生成。正在准备最终打包。",
    "PACKAGING_FINAL": "正在整理最终项目包和交付清单。",
    "FINAL_READY": "最终项目包已准备好，可以交付。",
    "WAITING_FOR_PROVIDER_QUOTA": "当前模型额度不足，请更换 provider 或稍后继续。",
    "NEEDS_USER_DECISION": "候选项目已准备好，需要你确认是否继续最终打包。",
    "FAILED_WITH_RECOVERY_OPTIONS": "本次生成没有完成，可选择重试、继续修复或取消。",
}


def _clean_message(text: str) -> str:
    cleaned = str(text or "")
    for term in FORBIDDEN_TERMS:
        cleaned = cleaned.replace(term, "")
    return cleaned.replace("  ", " ").strip()


def render_status(
    status: str,
    *,
    final_gate_passed: bool = False,
    can_retry: bool = True,
    can_continue: bool = True,
    can_cancel: bool = True,
    next_action: str = "",
    details: str = "",
) -> dict[str, Any]:
    public_status = str(status or "QUEUED").upper()
    if public_status == "FINAL_READY" and not final_gate_passed:
        public_status = "PACKAGING_FINAL"
    if public_status not in PUBLIC_STATUSES:
        public_status = "FAILED_WITH_RECOVERY_OPTIONS"
    message = _clean_message(details or MESSAGES[public_status])
    if public_status == "READY_FOR_REVIEW":
        message = message.replace("最终项目包已准备好", "候选项目已准备好")
    return {
        "public_status": public_status,
        "message": message,
        "can_retry": bool(can_retry),
        "can_continue": bool(can_continue),
        "can_cancel": bool(can_cancel),
        "next_action": next_action or ("confirm_final_packaging" if public_status == "READY_FOR_REVIEW" else ""),
    }


def render_from_internal(internal: dict[str, Any]) -> dict[str, Any]:
    status = str(internal.get("public_status") or internal.get("status") or "QUEUED")
    if "quota" in str(internal.get("reason", "")).lower():
        status = "WAITING_FOR_PROVIDER_QUOTA"
    return render_status(
        status,
        final_gate_passed=bool(internal.get("final_gate_passed")),
        can_retry=bool(internal.get("can_retry", True)),
        can_continue=bool(internal.get("can_continue", True)),
        can_cancel=bool(internal.get("can_cancel", True)),
        next_action=str(internal.get("next_action") or ""),
        details=str(internal.get("message") or ""),
    )


def write_sample(path: pathlib.Path) -> dict[str, Any]:
    sample = render_status("READY_FOR_REVIEW")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sample
