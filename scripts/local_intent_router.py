#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
from typing import Any


MEMORY_TITLE_MARKERS = (
    "requirement blueprint generator",
    "cgnk requirement blueprint generator",
    "需求蓝图生成器",
)

BLUEPRINT_PROJECT_TYPES = {"requirement_blueprint_generator"}

PROJECT_TYPE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("api_backend", "backend_service", ("api", "backend", "server", "接口", "后端", "服务端")),
    ("data_analysis_tool", "data_analysis", ("csv", "excel", "数据", "表格", "分析", "上传", "文件", "file")),
    ("reporting_application", "reporting", ("dashboard", "report", "analytics", "统计", "报表", "报告", "可视化", "图表")),
    ("media_tool", "media_processing", ("image", "video", "图片", "图像", "视频", "截图", "音频")),
    ("local_application", "local_tooling", ("本地", "local", "工具", "app", "应用", "桌面")),
)

FEATURE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("file_import", ("上传", "导入", "文件", "file", "upload", "import", "csv", "excel")),
    ("data_analysis", ("分析", "analysis", "analytics", "统计", "metrics")),
    ("statistics_report", ("统计", "报表", "报告", "report")),
    ("visualization", ("可视化", "图表", "曲线", "热力图", "dashboard", "chart", "visualization", "heatmap")),
    ("image_export", ("图片", "截图", "image", "screenshot", "png", "jpg")),
    ("pdf_export", ("pdf", "PDF")),
    ("local_runtime", ("本地", "local", "离线")),
)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def _has_blueprint_title(text: str) -> bool:
    return _contains_any(text, MEMORY_TITLE_MARKERS)


def _explicitly_requests_blueprint_generator(text: str) -> bool:
    lowered = str(text or "").lower()
    if "requirement blueprint generator" in lowered or "cgnk requirement blueprint generator" in lowered:
        return True
    if "需求蓝图生成器" in text:
        return True
    if "blueprint generator" in lowered and ("requirement" in lowered or "需求" in text):
        return True
    return False


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


def _is_memory_title_only_candidate(candidate: str, raw_message: str) -> bool:
    if not should_ignore_memory_title(candidate, raw_message):
        return False
    cleaned = _clean_text(candidate)
    lowered = cleaned.lower()
    return cleaned.startswith("#") or any(marker in lowered for marker in MEMORY_TITLE_MARKERS)


def extract_explicit_user_goal(raw_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(raw_message or "")
    candidates: list[dict[str, Any]] = []
    if context:
        for key in ("raw_user_message", "goal", "project_summary"):
            value = _clean_text(context.get(key, ""))
            if value:
                candidates.append({"text": value, "source": f"context.{key}"})
    for message in _extract_visible_user_messages(text):
        candidates.append({"text": message, "source": "visible_user_message_log"})
    summary = _extract_current_project_summary(text)
    if summary:
        candidates.append({"text": summary, "source": "current_project_summary"})
    cleaned = _clean_text(text)
    if cleaned:
        candidates.append({"text": cleaned, "source": "raw_message"})

    for candidate in candidates:
        text_value = _clean_text(candidate["text"])
        if text_value and not _is_memory_title_only_candidate(text_value, raw_message):
            return {
                "raw_user_message": text_value,
                "source": candidate["source"],
                "confidence": 0.86 if str(candidate["source"]).startswith("context.") else 0.74,
                "candidates": candidates[:8],
            }
    return {"raw_user_message": cleaned, "source": "raw_message", "confidence": 0.5, "candidates": candidates[:8]}


def should_ignore_memory_title(memory_text: str, raw_message: str) -> bool:
    if not _has_blueprint_title(str(memory_text or "")):
        return False
    return not _explicitly_requests_blueprint_generator(str(raw_message or ""))


def _extract_required_features(text: str) -> list[str]:
    features: list[str] = []
    for feature, terms in FEATURE_RULES:
        if _contains_any(text, terms):
            features.append(feature)
    return features


def _classify_non_blueprint(text: str) -> tuple[str, str]:
    for project_type, domain, terms in PROJECT_TYPE_RULES:
        if _contains_any(text, terms):
            return project_type, domain
    return "custom_application", "general_local_project"


def classify_project_type(raw_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    explicit = extract_explicit_user_goal(raw_message, context)
    raw_user_message = str(explicit.get("raw_user_message", raw_message or ""))
    if _explicitly_requests_blueprint_generator(raw_user_message):
        project_type = "requirement_blueprint_generator"
        domain = "product_planning"
        required_features = ["requirement_intake", "blueprint_generation", "artifact_export"]
    else:
        project_type, domain = _classify_non_blueprint(raw_user_message)
        required_features = _extract_required_features(raw_user_message)
    return {
        "project_type": project_type,
        "domain": domain,
        "required_features": required_features,
        "non_goals": [],
        "intent_source": "raw_user_message",
        "raw_user_message": raw_user_message,
        "confidence": float(explicit.get("confidence", 0.72)),
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
    expected_is_blueprint = expected_type in BLUEPRINT_PROJECT_TYPES
    if expected_type and not expected_is_blueprint:
        if _has_blueprint_title(readme_title):
            conflict_reasons.append("readme_title_is_requirement_blueprint_generator")
        if story_name and _has_blueprint_title(story_name):
            conflict_reasons.append("product_story_name_mismatch")
        if manifest_type in BLUEPRINT_PROJECT_TYPES:
            conflict_reasons.append("manifest_project_type_mismatch")

    return {
        "conflict": bool(conflict_reasons),
        "expected_project_type": expected_type,
        "readme_title": readme_title,
        "manifest_project_type": manifest_type,
        "product_story_product_name": story_name,
        "reasons": conflict_reasons,
    }
