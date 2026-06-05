#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_connectivity


LIST_FIELDS = (
    "frontend_plan",
    "backend_plan",
    "data_model",
    "first_version_scope",
    "assumptions",
    "soft_questions",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def unique_strings(values: list[Any], limit: int = 20) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out[-limit:]


def latest_user_text(session: dict[str, Any]) -> str:
    for message in reversed(session.get("messages", [])):
        if isinstance(message, dict) and str(message.get("role", "")) == "user":
            text = str(message.get("text", "")).strip()
            if text and not text.startswith("/"):
                return text
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    return str(whiteboard.get("project_summary", "")).strip()


def text_fingerprint(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:24]


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    compact = str(text or "").lower()
    return any(keyword.lower() in compact for keyword in keywords)


def first_sentence(text: str, limit: int = 220) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    return value[:limit] or "这个项目"


def summarize_locally(session: dict[str, Any], latest_text: str, *, reason: str = "project_update") -> dict[str, Any]:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    existing_summary = str(whiteboard.get("project_summary", "")).strip()
    summary = first_sentence(existing_summary or latest_text)
    if existing_summary and latest_text and latest_text not in existing_summary:
        summary = first_sentence(f"{existing_summary}；补充：{latest_text}", limit=360)

    frontend_plan: list[str] = []
    backend_plan: list[str] = []
    data_model: list[str] = []
    scope: list[str] = []
    assumptions: list[str] = []
    questions: list[str] = []

    text = latest_text or summary
    if contains_any(text, ("vn", "视觉小说", "故事", "剧情", "时间线", "背景", "立绘", "图片", "生成图片")):
        frontend_plan.extend(["时间线梳理视图", "角色/立绘管理", "背景生成与预览区", "场景卡片和故事逻辑检查"])
        backend_plan.extend(["本地项目状态存储", "图片生成适配层", "场景/角色/素材索引", "导出交付包"])
        data_model.extend(["scene", "character", "timeline_event", "asset_generation_job"])
        scope.extend(["第一版先做本地可运行 VN 项目助手", "支持时间线整理、背景生成、立绘生成和预览"])
        assumptions.extend(["图片生成先做可替换 provider 接口，生成结果落到本地素材库"])
    if contains_any(text, ("后台", "后端", "api", "数据库", "登录", "管理", "系统", "agent")):
        frontend_plan.extend(["管理页", "列表/详情视图", "筛选和状态反馈"])
        backend_plan.extend(["本地接口层", "数据读写模块", "任务状态记录", "错误恢复记录"])
        data_model.extend(["project", "task", "user_setting", "run_log"])
        assumptions.extend(["后端先采用本地数据存储，接口设计保持可替换"])
    if contains_any(text, ("前端", "界面", "gui", "页面", "预览", "可视化")):
        frontend_plan.extend(["主工作台", "预览面板", "设置区", "结果列表"])
        scope.extend(["第一版交付可直接打开和操作的界面"])
    if contains_any(text, ("截图", "测试", "报告", "可运行", "本地")):
        backend_plan.extend(["启动脚本", "基础自检", "交付清单"])
        scope.extend(["交付启动说明、测试结论和预览截图"])

    if not frontend_plan:
        frontend_plan = ["项目工作台", "输入与配置区", "结果预览区"]
    if not backend_plan:
        backend_plan = ["本地状态管理", "核心处理流程", "交付打包记录"]
    if not data_model:
        data_model = ["project", "requirement", "output_asset"]
    if not scope:
        scope = ["第一版先交付可运行的本地项目", "覆盖核心输入、处理、预览和交付"]
    if not assumptions:
        assumptions = ["先按本地可运行、可测试、可扩展的默认方案推进"]

    compact = re.sub(r"[\s，。,.!?！？]+", "", text)
    if len(compact) <= 8:
        questions = ["这个项目第一版最核心的使用场景是什么？", "需要偏向桌面工具、网页应用，还是 Telegram 内交互？"]
    elif not contains_any(text, ("本地", "网页", "app", "gui", "telegram", "桌面")):
        questions.append("第一版运行形态我先按本地网页处理，可以吗？")
    if contains_any(text, ("图片", "生成图片", "背景", "立绘")) and not contains_any(text, ("正经", "真实", "直接生成", "provider", "api")):
        questions.append("图片生成我先按真实图片生成接口预留，本地保存结果，可以吗？")

    confidence = 0.82
    if len(compact) <= 8:
        confidence = 0.55
    elif questions:
        confidence = 0.72

    soft_questions = unique_strings(questions, limit=2)
    frontend_plan = unique_strings(frontend_plan, limit=8)
    backend_plan = unique_strings(backend_plan, limit=8)
    data_model = unique_strings(data_model, limit=8)
    scope = unique_strings(scope, limit=6)
    assumptions = unique_strings(assumptions, limit=6)

    question_text = ""
    if soft_questions:
        question_text = "\n我先带着默认假设继续，不会卡住生成；需要你补的话只问这一点：" + "；".join(soft_questions)

    user_visible_reply = (
        f"我按项目需求开始拆：{summary}。\n"
        f"第一版先做：{'；'.join(scope[:3])}。\n"
        f"前端重点：{'；'.join(frontend_plan[:4])}。\n"
        f"后端重点：{'；'.join(backend_plan[:4])}。"
        f"{question_text}"
    )

    return {
        "kind": "BackendDialogueAnalysis",
        "status": "ok",
        "reason": reason,
        "project_summary": summary,
        "backend_memo": f"后台拆解: {summary}；前端={';'.join(frontend_plan[:4])}；后端={';'.join(backend_plan[:4])}",
        "frontend_plan": frontend_plan,
        "backend_plan": backend_plan,
        "data_model": data_model,
        "first_version_scope": scope,
        "assumptions": assumptions,
        "soft_questions": soft_questions,
        "ready_to_generate": True,
        "confidence": confidence,
        "user_visible_reply": user_visible_reply[:1500],
        "source": "local_heuristic",
        "updated_at": now(),
    }


def should_call_provider(session: dict[str, Any], latest_text: str, local: dict[str, Any], *, reason: str, api_budget: str) -> bool:
    if str(api_budget or "low").lower() in {"off", "none", "disabled"}:
        return False
    creds = check_connectivity._resolve_api_credentials()
    if not str(creds.get("api_key", "")).strip():
        return False
    budget = session.get("backend_dialogue_budget", {}) if isinstance(session.get("backend_dialogue_budget"), dict) else {}
    if budget.get("last_text_fingerprint") == text_fingerprint(latest_text) and budget.get("last_provider_status") == "ok":
        return False
    api_calls = int(budget.get("api_calls") or 0)
    if api_calls >= 1 and str(api_budget or "low").lower() == "low":
        return False
    if reason == "new_project_request":
        return len(latest_text.strip()) >= 70 or float(local.get("confidence") or 0) < 0.75
    if contains_any(latest_text, ("你怎么看", "方案", "架构", "分析", "拆解", "复杂")):
        return True
    return float(local.get("confidence") or 0) < 0.7


def extract_json_object(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    try:
        doc = json.loads(value)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", value, flags=re.S)
    if not match:
        return {}
    try:
        doc = json.loads(match.group(0))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def call_provider(session: dict[str, Any], latest_text: str, local: dict[str, Any], *, model: str, timeout: int) -> tuple[dict[str, Any] | None, str]:
    creds = check_connectivity._resolve_api_credentials()
    api_key = str(creds.get("api_key", "")).strip()
    root = str(creds.get("base_url", "")).rstrip("/")
    if not api_key or not root:
        return None, "missing credentials"
    prompt = (
        "你是轻量后台需求分析器，不生成项目文件，不宣布完成。"
        "根据用户最新需求和本地初稿，输出 JSON，字段只能包括: "
        "project_summary, frontend_plan, backend_plan, data_model, first_version_scope, assumptions, soft_questions, user_visible_reply。"
        "soft_questions 最多 2 个，必须是非阻塞问题。回复要自然，不能出现'我已记下'或'收到'。"
        f"\n用户最新需求: {latest_text[:4000]}"
        f"\n本地初稿: {json.dumps(local, ensure_ascii=False)[:6000]}"
    )
    if check_connectivity._is_gptsapi_base_url(root):
        endpoint = root + "/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
    else:
        endpoint = root + "/responses"
        payload = {
            "model": model,
            "input": prompt,
            "temperature": 0.2,
        }
    doc, error = check_connectivity._post_json(endpoint, payload, api_key, max(5, min(int(timeout), 60)))
    if error or not isinstance(doc, dict):
        return None, error or "empty response"
    parsed = extract_json_object(check_connectivity._extract_text(doc))
    if not parsed:
        return None, "provider returned non-json analysis"
    return parsed, ""


def merge_analysis(local: dict[str, Any], provider: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(local)
    if provider:
        for key in ("project_summary", "user_visible_reply"):
            value = str(provider.get(key, "")).strip()
            if value:
                merged[key] = value[:1500]
        for key in LIST_FIELDS:
            merged[key] = unique_strings(provider.get(key, []) if isinstance(provider.get(key), list) else [provider.get(key)], limit=8)
        if not merged.get("backend_memo"):
            merged["backend_memo"] = f"后台拆解: {merged.get('project_summary', '')}"
        merged["source"] = "provider_once_per_turn"
        merged["confidence"] = max(float(local.get("confidence") or 0), 0.86)
    merged["soft_questions"] = unique_strings(merged.get("soft_questions", []), limit=2)
    merged["ready_to_generate"] = True
    merged["updated_at"] = now()
    return merged


def update_session_from_analysis(session: dict[str, Any], analysis: dict[str, Any]) -> None:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    whiteboard["project_summary"] = str(analysis.get("project_summary", "")).strip() or str(whiteboard.get("project_summary", "")).strip()
    whiteboard["frontend_plan"] = unique_strings(analysis.get("frontend_plan", []), limit=12)
    whiteboard["backend_plan"] = unique_strings(analysis.get("backend_plan", []), limit=12)
    whiteboard["data_model"] = unique_strings(analysis.get("data_model", []), limit=12)
    whiteboard["first_version_plan"] = unique_strings(
        list(whiteboard.get("first_version_plan", []) if isinstance(whiteboard.get("first_version_plan"), list) else [])
        + list(analysis.get("first_version_scope", []) if isinstance(analysis.get("first_version_scope"), list) else []),
        limit=20,
    )
    whiteboard["default_assumptions"] = unique_strings(
        list(whiteboard.get("default_assumptions", []) if isinstance(whiteboard.get("default_assumptions"), list) else [])
        + list(analysis.get("assumptions", []) if isinstance(analysis.get("assumptions"), list) else []),
        limit=20,
    )
    whiteboard["open_questions"] = unique_strings(analysis.get("soft_questions", []), limit=2)
    whiteboard["soft_questions"] = unique_strings(analysis.get("soft_questions", []), limit=2)
    whiteboard["blocking_questions"] = []
    whiteboard["ready_to_generate"] = bool(analysis.get("ready_to_generate", True))
    whiteboard["backend_dialogue_updated_at"] = str(analysis.get("updated_at", now()))
    whiteboard["backend_dialogue_confidence"] = float(analysis.get("confidence") or 0)
    session["whiteboard"] = whiteboard
    session["backend_dialogue_analysis"] = analysis


def run_backend_dialogue_tick(
    session_dir: pathlib.Path,
    chat_id: int | str,
    session: dict[str, Any],
    *,
    model: str,
    timeout: int,
    reason: str,
    api_budget: str = "low",
) -> dict[str, Any]:
    del session_dir, chat_id
    if str(model or "").lower().startswith("gpt-test"):
        api_budget = "off"
    latest_text = latest_user_text(session)
    fingerprint = text_fingerprint(latest_text)
    budget = session.get("backend_dialogue_budget", {}) if isinstance(session.get("backend_dialogue_budget"), dict) else {}
    existing = session.get("backend_dialogue_analysis") if isinstance(session.get("backend_dialogue_analysis"), dict) else None
    if existing and budget.get("last_text_fingerprint") == fingerprint and budget.get("last_reason") == reason:
        reused = dict(existing)
        reused["reused"] = True
        reused["updated_at"] = now()
        return reused

    local = summarize_locally(session, latest_text, reason=reason)
    provider_doc: dict[str, Any] | None = None
    provider_error = ""
    provider_attempted = False
    if should_call_provider(session, latest_text, local, reason=reason, api_budget=api_budget):
        provider_attempted = True
        provider_doc, provider_error = call_provider(session, latest_text, local, model=model, timeout=timeout)

    analysis = merge_analysis(local, provider_doc)
    if provider_attempted and provider_error:
        analysis["status"] = "degraded"
        analysis["provider_error"] = provider_error[:500]
    else:
        analysis["status"] = "ok"
    analysis["reason"] = reason

    update_session_from_analysis(session, analysis)
    budget["last_tick_at"] = now()
    budget["last_text_fingerprint"] = fingerprint
    budget["last_reason"] = reason
    budget["last_provider_status"] = "ok" if provider_doc else ("failed" if provider_attempted else "skipped")
    if provider_attempted:
        budget["api_calls"] = int(budget.get("api_calls") or 0) + 1
        budget["last_model"] = model
        budget["last_api_error"] = provider_error[:500]
    session["backend_dialogue_budget"] = budget
    return analysis
