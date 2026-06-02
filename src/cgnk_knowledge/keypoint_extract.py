from __future__ import annotations

import hashlib
import re
from typing import Any

from .classify import classify_keypoint


CATEGORY_KEYWORDS = {
    "goal": ("目标", "我要", "我想要", "build", "构建"),
    "constraint": ("必须", "不能", "不要", "禁止", "只读", "do not", "never", "read-only", "no provider", "no db", "no sqlite"),
    "decision": ("决定", "核心原则", "架构", "module composition", "agent 从模块组合", "not fixed manually"),
    "requirement": ("需要", "功能", "实现", "must include", "required"),
    "correction": ("不是", "我不是要", "你说错了", "应该是", "改成", "现在目标是"),
    "open_question": ("?", "？", "open question", "待确认"),
    "next_step": ("next step", "下一步", "然后", "before final"),
    "test_result": ("commit", "tests passed", "validation passed", "benchmark", "测试结果", "验证结果"),
    "artifact_ref": ("artifact", "schemas/", "examples/", "tests/", "src/", ".json", ".py", "localhost", "http://127.0.0.1"),
    "module_mapping": ("module", "模块", "module contract"),
    "agent_mapping": ("agent", "AgentComposer", "generated agent"),
    "research_finding": ("research", "backend.research", "finding"),
}


def _stable_id(prefix: str, text: str, event_ids: list[str]) -> str:
    seed = "|".join([text.strip().lower(), *event_ids])
    return f"{prefix}_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def _split_points(text: str) -> list[str]:
    cleaned = str(text or "").replace("\r\n", "\n")
    candidates: list[str] = []
    for line in cleaned.splitlines():
        value = re.sub(r"^\s*[-*#\d.)]+\s*", "", line).strip()
        if value:
            candidates.extend(part.strip() for part in re.split(r"(?<=[。.!?？])\s+", value) if part.strip())
    return candidates


def _category_for(text: str) -> str | None:
    lowered = text.lower()
    matches = [cat for cat, keys in CATEGORY_KEYWORDS.items() if any(key.lower() in lowered for key in keys)]
    if "constraint" in matches:
        return "constraint"
    if "correction" in matches:
        return "correction"
    if "goal" in matches:
        return "goal"
    if "decision" in matches:
        return "decision"
    if "artifact_ref" in matches:
        return "artifact_ref"
    return matches[0] if matches else None


def _scope_for(text: str, session_state: dict[str, Any]) -> str:
    lowered = text.lower()
    if "ctcp" in lowered:
        return "project.ctcp"
    if "cgnk" in lowered or session_state.get("project") == "CGNK":
        return "project.cgnk"
    if "agent" in lowered:
        return "agent"
    if "module" in lowered or "模块" in text:
        return "module"
    return "project"


def _source_event_ids(session_state: dict[str, Any]) -> list[str]:
    ids = session_state.get("current_event_ids") or session_state.get("source_event_ids") or []
    if isinstance(ids, str):
        return [ids]
    return [str(row) for row in ids]


def extract_keypoints_from_turn(session_state: dict[str, Any] | None, user_message: str, assistant_message: str | None = None) -> dict[str, Any]:
    state = session_state or {}
    source_event_ids = _source_event_ids(state)
    diagnostics: list[dict[str, Any]] = []
    keypoints: list[dict[str, Any]] = []

    for role, message in (("user", user_message), ("assistant", assistant_message or "")):
        for point in _split_points(message):
            category = _category_for(point)
            if not category and len(point) > 160:
                category = "requirement"
            if not category:
                classified = classify_keypoint(point, source=role)
                if classified["importance"] == "noise":
                    continue
                category = classified["category"]
            classification = classify_keypoint(point, category=category, source=role)
            keypoints.append(
                {
                    "kind": "KeyPoint",
                    "id": _stable_id("kp", point, source_event_ids + [role]),
                    "category": classification["category"],
                    "text": point,
                    "source_event_ids": source_event_ids,
                    "scope": _scope_for(point, state),
                    "importance": classification["importance"],
                    "need_state": classification["need_state"],
                    "retention": classification["retention"],
                    "review_state": classification["review_state"],
                    "confidence": classification["confidence"],
                    "status": classification["status"],
                    "tags": sorted(set(re.findall(r"\b(?:CTCP|CGNK|AgentComposer|WorkGraph|Gate|module|agent|schema)\b", point, flags=re.I))),
                    "diagnostics": classification["diagnostics"],
                }
            )

    unique: dict[str, dict[str, Any]] = {}
    for item in keypoints:
        unique.setdefault(item["id"], item)
    return {"kind": "KeyPointExtractionResult", "keypoints": [unique[k] for k in sorted(unique)], "diagnostics": diagnostics}
