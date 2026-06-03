#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
from typing import Any


CSGO2_REQUIRED_FEATURES = [
    "csgo2_demo_import",
    "mouse_movement_analysis",
    "click_analysis",
    "keyboard_input_analysis",
    "view_angle_analysis",
    "crosshair_movement_analysis",
    "operation_statistics",
    "heatmap_visualization",
    "frequency_curve",
    "image_report_export",
    "pdf_report_export",
]

CSGO2_NON_GOALS = [
    "deep_ml_cheat_detection",
    "final_cheat_verdict",
]

CSGO2_KEYWORDS = (
    "csgo2",
    "cs2",
    "demo",
    ".dem",
    "鼠标",
    "mouse",
    "点击",
    "click",
    "键盘",
    "keyboard",
    "视角",
    "view angle",
    "准星",
    "crosshair",
    "热力图",
    "heatmap",
    "操作频率",
    "frequency",
    "pdf",
)

MEMORY_TITLE_MARKERS = (
    "requirement blueprint generator",
    "cgnk requirement blueprint generator",
)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _looks_like_csgo2_request(text: str) -> bool:
    lowered = text.lower()
    hits = sum(1 for keyword in CSGO2_KEYWORDS if keyword.lower() in lowered)
    has_game = any(keyword in lowered for keyword in ("csgo2", "cs2", "demo", ".dem"))
    has_telemetry = any(keyword in lowered for keyword in ("鼠标", "mouse", "键盘", "keyboard", "视角", "准星", "crosshair", "热力图", "操作频率"))
    return has_game and has_telemetry and hits >= 3


def _extract_visible_user_messages(text: str) -> list[str]:
    messages: list[str] = []
    marker = "Visible User Message Log"
    if marker not in text:
        return messages
    tail = text.split(marker, 1)[1]
    for line in tail.splitlines():
        stripped = line.strip()
        match = re.match(r"^\d+\.\s*(.+)$", stripped)
        if match:
            messages.append(match.group(1).strip())
        elif stripped.startswith("## ") and messages:
            break
    return messages


def _extract_current_project_summary(text: str) -> str:
    marker = "Current Project Summary"
    if marker not in text:
        return ""
    tail = text.split(marker, 1)[1]
    lines: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## ") and lines:
            break
        if stripped.startswith("#") or stripped.startswith("-"):
            continue
        lines.append(stripped)
    return _clean_text(" ".join(lines))


def extract_explicit_user_goal(raw_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(raw_message or "")
    candidates: list[dict[str, Any]] = []
    for message in _extract_visible_user_messages(text):
        candidates.append({"text": message, "source": "visible_user_message_log"})
    summary = _extract_current_project_summary(text)
    if summary:
        candidates.append({"text": summary, "source": "current_project_summary"})
    if context:
        for key in ("raw_user_message", "goal", "project_summary"):
            value = _clean_text(context.get(key, ""))
            if value:
                candidates.insert(0, {"text": value, "source": f"context.{key}"})
    cleaned = _clean_text(text)
    if cleaned:
        candidates.append({"text": cleaned, "source": "raw_message"})

    for candidate in candidates:
        if _looks_like_csgo2_request(candidate["text"]):
            return {
                "raw_user_message": candidate["text"],
                "source": candidate["source"],
                "confidence": 1.0,
                "candidates": candidates[:8],
            }

    for candidate in candidates:
        text_value = _clean_text(candidate["text"])
        if text_value and not should_ignore_memory_title(text_value, raw_message):
            return {
                "raw_user_message": text_value,
                "source": candidate["source"],
                "confidence": 0.72,
                "candidates": candidates[:8],
            }
    return {"raw_user_message": cleaned, "source": "raw_message", "confidence": 0.5, "candidates": candidates[:8]}


def should_ignore_memory_title(memory_text: str, raw_message: str) -> bool:
    memory_lower = str(memory_text or "").lower()
    if not any(marker in memory_lower for marker in MEMORY_TITLE_MARKERS):
        return False
    return _looks_like_csgo2_request(str(raw_message or ""))


def classify_project_type(raw_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    explicit = extract_explicit_user_goal(raw_message, context)
    raw_user_message = str(explicit.get("raw_user_message", raw_message or ""))
    if _looks_like_csgo2_request(raw_user_message) or _looks_like_csgo2_request(raw_message):
        return {
            "project_type": "game_demo_telemetry_analyzer",
            "domain": "esports_demo_analysis",
            "required_features": list(CSGO2_REQUIRED_FEATURES),
            "non_goals": list(CSGO2_NON_GOALS),
            "intent_source": "raw_user_message",
            "raw_user_message": raw_user_message,
            "confidence": 1.0,
        }
    return {
        "project_type": "unknown_project_type",
        "domain": "unknown",
        "required_features": [],
        "non_goals": [],
        "intent_source": "raw_user_message",
        "raw_user_message": raw_user_message,
        "confidence": float(explicit.get("confidence", 0.5)),
    }


def _read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _readme_title(readme_text: str) -> str:
    for line in readme_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def detect_project_type_conflict(expected: dict[str, Any], generated_project_dir: pathlib.Path) -> dict[str, Any]:
    project_dir = pathlib.Path(generated_project_dir)
    readme_text = _read_text(project_dir / "README.md")
    readme_title = _readme_title(readme_text)
    manifest = _read_json(project_dir / "project_manifest.json")
    expected_type = str(expected.get("project_type", "")).strip()
    manifest_type = str(manifest.get("project_type") or manifest.get("type") or "").strip()
    story_name = str(expected.get("product_name") or expected.get("product_story", {}).get("product_name", "")).strip()

    conflict_reasons: list[str] = []
    if expected_type == "game_demo_telemetry_analyzer":
        lowered_title = readme_title.lower()
        if "requirement blueprint generator" in lowered_title:
            conflict_reasons.append("readme_title_is_requirement_blueprint_generator")
        if manifest_type and manifest_type not in {"game_demo_telemetry_analyzer", "esports_demo_analysis"}:
            conflict_reasons.append("manifest_project_type_mismatch")
        if story_name and "blueprint generator" in story_name.lower():
            conflict_reasons.append("product_story_name_mismatch")

    return {
        "conflict": bool(conflict_reasons),
        "expected_project_type": expected_type,
        "readme_title": readme_title,
        "manifest_project_type": manifest_type,
        "product_story_product_name": story_name,
        "reasons": conflict_reasons,
    }
