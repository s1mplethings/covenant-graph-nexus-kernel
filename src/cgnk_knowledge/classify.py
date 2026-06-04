from __future__ import annotations

import re
from typing import Any


DIAG_CLASSIFICATION = "CGNK_KNOWLEDGE_CLASSIFICATION_APPLIED"

HARD_CONSTRAINTS = (
    "必须",
    "不能",
    "不要",
    "禁止",
    "只读",
    "不允许",
    "do not",
    "must",
    "never",
    "read-only",
    "no provider",
    "no cgkn modification",
    "do not modify cgkn",
    "no workspace write",
    "no db/sqlite",
    "no sqlite",
    "no zip",
    "no final_output",
    "no project_output",
)

CORRECTIONS = (
    "不是这个",
    "不是 work in cgkn",
    "我不是要",
    "你说错了",
    "应该是",
    "改成",
    "现在目标是",
)

ARCHITECTURE = (
    "架构",
    "设计",
    "核心原则",
    "agent 从模块组合",
    "skill 是缓存",
    "module contract",
    "agentcomposer",
    "workgraph",
    "gate",
    "module-driven",
    "module composition",
)

GOALS = ("我想要", "我要", "需要", "目标", "功能", "实现", "构建", "设计", "build", "goal", "requirement")
TEST_REPORTS = ("commit", "tests passed", "validation passed", "full suite", "benchmark", "report", "测试结果", "验证结果")
TEMPORARY = ("http://127.0.0.1", "localhost", "port", "gui 地址", "%temp%", "temp path", "temporary report", "one-off run data")
REJECTED = ("不要这样", "不是这个方向", "这个不对", "不要改 cgkn", "之前那个错了")
NOISE = ("hi", "hello", "thanks", "谢谢", "好的", "ok", "嗯")


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def _explicit_user(source: str) -> bool:
    return str(source or "").lower() in {"user", "explicit_user", "user_message"}


def classify_keypoint(text: str, category: str | None = None, source: str = "auto") -> dict[str, Any]:
    """Classify one extracted key point using deterministic local rules only."""
    value = re.sub(r"\s+", " ", str(text or "").strip())
    lowered = value.lower()
    explicit = _explicit_user(source)
    result: dict[str, Any] = {
        "category": category or "requirement",
        "importance": "medium",
        "need_state": "unknown",
        "retention": "keep",
        "review_state": "accepted" if explicit else "auto_extracted",
        "confidence": 0.72 if not explicit else 0.95,
        "status": "active",
        "diagnostics": [{"code": DIAG_CLASSIFICATION, "severity": "info", "message": "rule-based classification applied"}],
    }

    if not value or lowered in NOISE or len(value) <= 2:
        result.update(
            {
                "category": category or "requirement",
                "importance": "noise",
                "need_state": "not_needed",
                "retention": "discard",
                "review_state": "auto_extracted",
                "confidence": 0.4,
            }
        )
        return result

    if _contains(value, REJECTED):
        result.update(
            {
                "category": category or "correction",
                "importance": "critical",
                "need_state": "not_needed",
                "retention": "archive",
                "review_state": "rejected",
                "status": "retracted",
            }
        )
        return result

    if _contains(value, HARD_CONSTRAINTS):
        result.update(
            {
                "category": category or "constraint",
                "importance": "critical",
                "need_state": "needed_now",
                "retention": "keep",
                "review_state": "accepted" if explicit else "auto_extracted",
            }
        )
        return result

    if _contains(value, CORRECTIONS):
        result.update(
            {
                "category": category or "correction",
                "importance": "critical" if "cgkn" in lowered or "目标" in value else "high",
                "need_state": "needed_now",
                "retention": "keep",
                "review_state": "accepted",
            }
        )
        return result

    if _contains(value, ARCHITECTURE):
        result.update(
            {
                "category": category or "decision",
                "importance": "high",
                "need_state": "needed_now" if explicit else "needed_later",
                "retention": "keep",
                "review_state": "accepted" if explicit else "auto_extracted",
            }
        )
        return result

    if _contains(value, GOALS):
        result.update(
            {
                "category": category or "goal",
                "importance": "high",
                "need_state": "needed_now",
                "retention": "keep",
                "review_state": "accepted" if explicit else "auto_extracted",
            }
        )
        return result

    if _contains(value, TEST_REPORTS):
        result.update(
            {
                "category": category or "test_result",
                "importance": "medium",
                "need_state": "reference_only",
                "retention": "compress",
                "review_state": "accepted" if explicit else "auto_extracted",
            }
        )
        return result

    if _contains(value, TEMPORARY):
        result.update(
            {
                "category": category or "artifact_ref",
                "importance": "low",
                "need_state": "reference_only",
                "retention": "ephemeral",
                "review_state": "auto_extracted",
            }
        )
        return result

    return result
