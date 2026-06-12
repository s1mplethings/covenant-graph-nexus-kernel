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
import capability_strategy
import local_image_model_discovery
import local_model_router
import public_narration


LIST_FIELDS = (
    "frontend_plan",
    "backend_plan",
    "data_model",
    "first_version_scope",
    "assumptions",
    "soft_questions",
    "missing_required_inputs",
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


COMPLEX_DOMAIN_KEYWORDS = (
    "csgo",
    "csgo2",
    "cs2",
    "demo",
    "鉴挂",
    "反作弊",
    "鼠标",
    "键盘",
    "行为分析",
    "模型",
    "数据集",
    "视频",
    "图像",
)

EVIDENCE_REVIEW_KEYWORDS = (
    "图片",
    "视频",
    "截图",
    "可视化",
    "demo",
    "csgo",
    "csgo2",
    "cs2",
    "鉴挂",
    "鼠标键盘动作",
    "视觉信息",
    "模型效果",
    "识别结果",
)


def question_answered_by_text(question: str, text: str) -> bool:
    question_text = str(question or "").lower()
    answer_text = str(text or "").lower()
    if not question_text.strip() or not answer_text.strip():
        return False
    if any(token in question_text for token in ("交付重点", "界面", "文件导出", "自动化流程")):
        return contains_any(answer_text, ("界面", "ui", "页面", "自动化", "流程", "导出", "文件"))
    if any(token in question_text for token in ("运行方式", "本地网页", "本地工具", "桌面", "命令行")):
        return contains_any(answer_text, ("本地", "网页", "桌面", "cli", "命令行", "telegram", "服务端"))
    if any(token in question_text for token in ("图片", "模型", "接口", "api", "后端", "comfyui", "sd_model_dir")):
        return contains_any(answer_text, ("本地模型", "api", "comfyui", "automatic1111", "sd", "分开", "统一模型", "预留接口", "先预留"))
    if any(token in question_text for token in ("优先", "模块", "先做", "第一版")):
        return contains_any(answer_text, ("一开始说的", "都要", "按默认", "先核心", "核心功能", "按当前"))
    return False


def resolve_answered_questions(existing_questions: list[Any], latest_text: str) -> list[str]:
    return [str(question).strip() for question in existing_questions if str(question).strip() and not question_answered_by_text(str(question), latest_text)]


def downgrade_unresolved_config_questions_to_assumptions(questions: list[str]) -> tuple[list[str], list[str]]:
    remaining: list[str] = []
    assumptions: list[str] = []
    config_terms = (
        "模型",
        "api",
        "key",
        "路径",
        "目录",
        "后端",
        "comfyui",
        "automatic1111",
        "sd_model_dir",
        "数据集",
        "示例文件",
        "风格",
        "触发方式",
        "导出格式",
    )
    for question in questions:
        if contains_any(question, config_terms):
            assumptions.append(f"{question}；先按可配置入口和验收限制处理，缺少真实配置时不宣称完整能力通过")
        else:
            remaining.append(question)
    return remaining, assumptions


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
    critical_questions: list[str] = []
    missing_required_inputs: list[str] = []
    local_image_discovery: dict[str, Any] = {}

    text = latest_text or summary
    context_text = "\n".join(item for item in (existing_summary, latest_text, summary) if str(item or "").strip())
    is_vn_domain = contains_any(context_text, ("vn", "视觉小说", "故事", "剧情", "时间线", "背景", "立绘"))
    is_cs_domain = contains_any(context_text, ("csgo", "csgo2", "cs2", "鉴挂", "反作弊", "鼠标键盘", "视角异常", "命中事件"))
    complex_domain = is_cs_domain or (contains_any(context_text, COMPLEX_DOMAIN_KEYWORDS) and not is_vn_domain)
    requires_user_evidence_review = contains_any(context_text, EVIDENCE_REVIEW_KEYWORDS)
    strategy = capability_strategy.build_capability_strategy(context_text, SCRIPTS_DIR.parent)
    if strategy.get("local_image_model_discovery"):
        local_image_discovery = strategy.get("local_image_model_discovery", {})
    if contains_any(context_text, ("vn", "视觉小说", "故事", "剧情", "时间线", "背景", "立绘", "图片", "生成图片")):
        frontend_plan.extend(["时间线梳理视图", "角色/立绘管理", "背景生成预览区", "立绘生成预览区", "场景卡片和故事逻辑检查"])
        backend_plan.extend(["本地项目状态存储", "背景图片生成适配层", "角色立绘生成适配层", "图片生成：背景和立绘独立任务编排", "场景/角色/素材索引", "导出交付包"])
        data_model.extend(["scene", "character", "timeline_event", "background_generation_job", "sprite_generation_job"])
        scope.extend(["第一版先做本地可运行 VN 项目助手", "支持时间线整理、背景生成、立绘生成和预览", "背景和立绘分开生成、分开管理、分开验收"])
        assumptions.extend([
            "图片生成先做可替换接口，生成结果落到本地素材库",
            "背景图和角色立绘使用独立任务与独立验收记录",
            "占位图、纯色图或降级预览不能算真实背景/立绘验收通过",
        ])
        critical_questions, local_image_discovery = local_image_model_discovery.critical_questions_for_text(context_text, SCRIPTS_DIR.parent)
        if local_image_discovery.get("checked"):
            backend_plan.append("本地图片模型能力探测（ComfyUI/AUTOMATIC1111/SD_MODEL_DIR）")
        if critical_questions:
            assumptions.append("本地图片模型未配置时记录为验收限制；占位图、纯色图或降级预览不能算真实背景/立绘通过")
        elif local_image_discovery.get("available"):
            assumptions.append("背景和立绘按已发现的本地图片模型后端分开生成，并保留缺失能力报告")
    if strategy.get("capabilities"):
        backend_plan.append("核心能力识别和高级实现路线筛选")
        for target in strategy.get("research_targets", [])[:4]:
            capability = target.get("capability", {}) if isinstance(target, dict) else {}
            label = str(capability.get("label", "")).strip()
            if label:
                scope.append(f"核心能力：{label}")
        critical_questions = unique_strings(
            critical_questions + list(strategy.get("critical_questions", []) if isinstance(strategy.get("critical_questions"), list) else []),
            limit=4,
        )
        assumptions.extend(strategy.get("acceptance_criteria", []) if isinstance(strategy.get("acceptance_criteria"), list) else [])
    if contains_any(context_text, ("后台", "后端", "api", "数据库", "登录", "管理", "系统", "agent")):
        frontend_plan.extend(["管理页", "列表/详情视图", "筛选和状态反馈"])
        backend_plan.extend(["本地接口层", "数据读写模块", "任务状态记录", "错误恢复记录"])
        data_model.extend(["project", "task", "user_setting", "run_log"])
        assumptions.extend(["后端先采用本地数据存储，接口设计保持可替换"])
    if contains_any(context_text, ("前端", "界面", "gui", "页面", "预览", "可视化")):
        frontend_plan.extend(["主工作台", "预览面板", "设置区", "结果列表"])
        scope.extend(["第一版交付可直接打开和操作的界面"])
    if contains_any(context_text, ("截图", "测试", "报告", "可运行", "本地")):
        backend_plan.extend(["启动脚本", "基础自检", "交付清单"])
        scope.extend(["交付启动说明、测试结论和预览截图"])
    if complex_domain:
        frontend_plan.extend(["分析结果工作台", "时间线/事件查看", "风险提示视图"])
        backend_plan.extend(["真实输入文件解析接口", "特征提取流程", "验证证据记录", "样例数据检查"])
        data_model.extend(["demo_file", "input_event", "visual_signal", "risk_assessment"])
        scope.extend(["第一版先做框架版/示例版分析流程，缺少真实输入时不宣称完成真实验证"])
        assumptions.append("缺少真实 demo 或样例输入时，只能交付框架版/示例版并在限制中标记未完成真实验证")
        missing_required_inputs.extend(
            [
                "实际 demo 文件或公开 demo 示例",
                "判别标准或疑似外挂行为定义",
                "期望输出形式，例如报告、时间线、可视化或风险评分",
            ]
        )
        questions.extend(
            [
                "是否可以提供实际 demo 文件或公开示例？",
                "鉴挂判别主要看动作规律、视角异常、命中事件，还是综合评分？",
                "第一版输出要偏报告、时间线可视化，还是风险评分？",
            ]
        )

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
    short_request = len(compact) <= 8
    intent_context = context_text.lower()
    has_project_goal = contains_any(intent_context, ("做", "帮我", "想要", "需要", "开发", "实现", "搭建", "创建")) and contains_any(
        intent_context,
        ("工具", "系统", "项目", "助手", "平台", "后台", "应用", "app", "网站", "程序", "服务"),
    )
    has_core_capability = contains_any(
        intent_context,
        ("管理", "生成", "分析", "导出", "自动化", "预览", "处理", "识别", "编辑", "整理", "导入", "截取", "报告", "对接", "api", "转换", "配置", "测试"),
    )
    run_shape_unclear = not contains_any(context_text, ("本地", "网页", "app", "gui", "telegram", "桌面", "命令行", "cli", "小程序"))
    output_shape_unclear = not contains_any(context_text, ("界面", "gui", "桌面", "网页", "文件", "导出", "自动化", "流程", "api", "报表", "工具", "时间线", "背景", "立绘"))
    actionable_project_request = has_project_goal and has_core_capability
    if actionable_project_request:
        run_shape_unclear = False
        output_shape_unclear = False
    needs_direction_confirmation = bool(short_request or not has_project_goal or not has_core_capability)
    if short_request:
        questions = ["这个项目第一版最核心的使用场景是什么？"]
        if run_shape_unclear:
            questions.append("第一版我先按本地网页/本地工具处理，可以吗？")
        if output_shape_unclear:
            questions.append("交付重点是界面、文件导出、还是自动化流程？")
    elif not contains_any(context_text, ("本地", "网页", "app", "gui", "telegram", "桌面")):
        questions.append("第一版我先按本地网页/本地工具处理，可以吗？")
    if not short_request and output_shape_unclear:
        questions.append("交付重点是界面、文件导出、还是自动化流程？")
    if contains_any(context_text, ("图片", "生成图片", "背景", "立绘")) and not contains_any(context_text, ("正经", "真实", "直接生成", "provider", "api", "本地模型")):
        questions.append("图片生成我先按真实图片生成接口预留，本地保存结果，可以吗？")
    existing_questions: list[Any] = []
    for key in ("soft_questions", "critical_questions", "open_questions"):
        value = whiteboard.get(key)
        if isinstance(value, list):
            existing_questions.extend(value)
    questions = unique_strings(resolve_answered_questions(existing_questions, latest_text) + resolve_answered_questions(questions, latest_text), limit=8)
    questions, config_assumptions = downgrade_unresolved_config_questions_to_assumptions(questions)
    assumptions.extend(config_assumptions)
    if actionable_project_request:
        needs_direction_confirmation = False

    confidence = 0.82
    if len(compact) <= 8:
        confidence = 0.55
    elif complex_domain:
        confidence = 0.62
    elif questions:
        confidence = 0.72

    critical_questions = unique_strings(critical_questions, limit=3)
    soft_questions = unique_strings(questions, limit=3)
    missing_required_inputs = unique_strings(missing_required_inputs, limit=6)
    domain_risk_level = "high" if complex_domain else ("medium" if needs_direction_confirmation else "low")
    recommended_next_action = "ask_user" if domain_risk_level == "high" or missing_required_inputs else ("wait_for_confirmation" if needs_direction_confirmation or soft_questions or critical_questions else "can_start")
    start_allowed_with_assumptions = True
    frontend_plan = unique_strings(frontend_plan, limit=8)
    backend_plan = unique_strings(backend_plan, limit=8)
    data_model = unique_strings(data_model, limit=8)
    scope = unique_strings(scope, limit=6)
    assumptions = unique_strings(assumptions, limit=6)
    required_capabilities = unique_strings(
        [
            item
            for item, tokens in (
                ("内容/素材生成", ("生成", "图片", "图像", "背景", "立绘", "视频", "音频")),
                ("视频或媒体处理", ("视频", "截取", "剪辑", "片段")),
                ("外部 API 对接", ("api", "接口", "对接")),
                ("自动化流程", ("自动化", "流程", "触发")),
                ("数据分析/识别", ("分析", "识别", "数据集", "训练")),
                ("导出与报告", ("导出", "报告", "文件")),
                ("界面预览", ("界面", "gui", "页面", "预览")),
            )
            if contains_any(context_text, tokens)
        ],
        limit=8,
    )
    delivery_requirements = unique_strings(
        [
            item
            for item, tokens in (
                ("可运行项目包", ("本地", "可运行", "项目", "工具", "系统", "助手")),
                ("界面截图或预览证据", ("界面", "gui", "页面", "预览", "截图")),
                ("生成素材证据", ("生成", "图片", "图像", "背景", "立绘", "视频", "音频")),
                ("导出结果或报告", ("导出", "报告", "文件")),
                ("测试报告", ("测试", "验收")),
            )
            if contains_any(context_text, tokens)
        ],
        limit=8,
    )
    acceptance_criteria = unique_strings(
        [
            "缺少真实模型、外部 API、媒体后端或数据集时，只能交付配置入口、适配层、测试框架和限制说明",
            "占位图、纯色图、降级预览或模拟结果不能算真实核心能力验收通过",
        ]
        if contains_any(context_text, ("模型", "api", "图片", "图像", "视频", "音频", "数据集", "训练", "生成", "识别"))
        else [],
        limit=6,
    )
    missing_config = unique_strings(
        [
            item
            for item, tokens in (
                ("模型路径或本地/外部生成后端配置", ("模型", "图片", "图像", "背景", "立绘", "生成")),
                ("外部 API key 或接口地址", ("api", "接口", "对接")),
                ("真实数据集或示例文件", ("数据集", "示例文件", "训练", "真实数据")),
                ("媒体处理后端配置", ("视频", "音频", "截取", "剪辑")),
            )
            if contains_any(context_text, tokens)
        ],
        limit=8,
    )
    known_limits = unique_strings(acceptance_criteria + [f"未配置：{item}" for item in missing_config], limit=10)

    question_text = ""
    if critical_questions:
        question_text = "\n这里有一个关键配置要确认：" + "；".join(critical_questions)
    if soft_questions:
        question_text += "\n需要你确认或补充：" + "；".join(soft_questions)

    if needs_direction_confirmation:
        suggested_confirmation_reply = "你可以补充这些信息；如果想先做框架版，也可以回复“开始生成”或“按默认假设开始”，我会把缺少真实验证写进限制"
        user_visible_reply = (
            f"我先按这个方向整理第一版范围：{summary}。\n"
            f"第一版默认假设：{'；'.join(assumptions[:3])}。\n"
            f"第一版会做：{'；'.join(scope[:3])}。\n"
            f"现在缺少几个会影响质量的点：{'；'.join(soft_questions[:3]) if soft_questions else '暂无必须确认的问题'}。\n"
            f"{suggested_confirmation_reply}。"
            f"{question_text}"
        )
    else:
        suggested_confirmation_reply = ""
        user_visible_reply = (
            f"我先按这个方向整理第一版范围：{summary}。\n"
            f"第一版会做：{'；'.join(scope[:3])}。\n"
            f"界面和预览重点：{'；'.join(frontend_plan[:4])}。\n"
            f"技术路线重点：{'；'.join(backend_plan[:4])}。"
            f"{question_text}"
        )
    if requires_user_evidence_review:
        user_visible_reply += "\n开始后我会先准备测试代码、测试命令和预览证据。等中间结果出来后，我会先发给你判断，再进入最终打包。"

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
        "required_capabilities": required_capabilities,
        "delivery_requirements": delivery_requirements,
        "acceptance_criteria": acceptance_criteria,
        "known_limits": known_limits,
        "missing_config": missing_config,
        "soft_questions": soft_questions,
        "critical_questions": critical_questions,
        "missing_required_inputs": missing_required_inputs,
        "domain_risk_level": domain_risk_level,
        "recommended_next_action": recommended_next_action,
        "start_allowed_with_assumptions": start_allowed_with_assumptions,
        "capability_strategy": strategy,
        "local_image_model_discovery": local_image_discovery,
        "ready_to_generate": True,
        "requires_user_evidence_review": requires_user_evidence_review,
        "needs_direction_confirmation": needs_direction_confirmation,
        "suggested_confirmation_reply": suggested_confirmation_reply,
        "confidence": confidence,
        "user_visible_reply": public_narration.redact_internal_terms(user_visible_reply)[:1500],
        "source": "local_heuristic",
        "updated_at": now(),
    }


def should_call_provider(session: dict[str, Any], latest_text: str, local: dict[str, Any], *, reason: str, api_budget: str) -> bool:
    if str(api_budget or "low").lower() in {"off", "none", "disabled"}:
        return False
    local_enabled = local_model_router.task_enabled("backend_dialogue")
    creds = check_connectivity._resolve_api_credentials()
    if not local_enabled and not str(creds.get("api_key", "")).strip():
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
    return local_model_router.extract_json(text) or {}


def backend_dialogue_prompt(latest_text: str, local: dict[str, Any]) -> str:
    return (
        "你是轻量后台需求分析器，不生成项目文件，不宣布完成。"
        "根据用户最新需求和本地初稿，输出 JSON，字段只能包括: "
        "project_summary, frontend_plan, backend_plan, data_model, first_version_scope, assumptions, soft_questions, critical_questions, missing_required_inputs, domain_risk_level, recommended_next_action, start_allowed_with_assumptions, needs_direction_confirmation, requires_user_evidence_review, suggested_confirmation_reply, user_visible_reply。"
        "soft_questions 最多 3 个，必须是非阻塞问题。回复要自然，不能出现'我已记下'或'收到'。"
        "critical_questions 只用于本地模型、凭据、外部能力等关键配置缺口；不能作为生成硬门禁。"
        f"\n用户最新需求: {latest_text[:4000]}"
        f"\n本地初稿: {json.dumps(local, ensure_ascii=False)[:6000]}"
    )


def call_provider(session: dict[str, Any], latest_text: str, local: dict[str, Any], *, model: str, timeout: int) -> tuple[dict[str, Any] | None, str]:
    prompt = backend_dialogue_prompt(latest_text, local)
    local_result = local_model_router.call_json_task(
        "backend_dialogue",
        "Return strict JSON for lightweight project requirement analysis. Do not write files.",
        prompt,
        timeout,
    )
    if local_result.get("ok") and isinstance(local_result.get("json"), dict):
        parsed = dict(local_result["json"])
        parsed["_provider_source"] = "local_model"
        parsed["_local_model_provider"] = local_result.get("provider", "")
        parsed["_local_model_name"] = local_result.get("model", "")
        return parsed, ""

    creds = check_connectivity._resolve_api_credentials()
    api_key = str(creds.get("api_key", "")).strip()
    root = str(creds.get("base_url", "")).rstrip("/")
    if not api_key or not root:
        return None, str(local_result.get("error") or "missing credentials")
    endpoint = check_connectivity._openai_compatible_endpoint(root)
    payload = check_connectivity._build_openai_compatible_payload(
        root,
        {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
    )
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
        provider_source = str(provider.get("_provider_source") or "provider_once_per_turn")
        for key in ("project_summary", "user_visible_reply"):
            value = str(provider.get(key, "")).strip()
            if value:
                merged[key] = value[:1500]
        for key in LIST_FIELDS:
            merged[key] = unique_strings(provider.get(key, []) if isinstance(provider.get(key), list) else [provider.get(key)], limit=8)
        provider_critical = provider.get("critical_questions", [])
        if isinstance(provider_critical, list):
            merged["critical_questions"] = unique_strings(
                list(local.get("critical_questions", []) if isinstance(local.get("critical_questions"), list) else [])
                + provider_critical,
                limit=3,
            )
        if not merged.get("backend_memo"):
            merged["backend_memo"] = f"后台拆解: {merged.get('project_summary', '')}"
        if "needs_direction_confirmation" in provider:
            merged["needs_direction_confirmation"] = bool(provider.get("needs_direction_confirmation"))
        if "requires_user_evidence_review" in provider:
            merged["requires_user_evidence_review"] = bool(provider.get("requires_user_evidence_review")) or bool(local.get("requires_user_evidence_review"))
        for key in ("missing_required_inputs",):
            if isinstance(provider.get(key), list):
                merged[key] = unique_strings(
                    list(local.get(key, []) if isinstance(local.get(key), list) else []) + list(provider.get(key, [])),
                    limit=6,
                )
        for key in ("domain_risk_level", "recommended_next_action"):
            value = str(provider.get(key, "")).strip()
            if value:
                merged[key] = value[:80]
        if "start_allowed_with_assumptions" in provider:
            merged["start_allowed_with_assumptions"] = bool(provider.get("start_allowed_with_assumptions"))
        if str(provider.get("suggested_confirmation_reply", "")).strip():
            merged["suggested_confirmation_reply"] = str(provider.get("suggested_confirmation_reply", "")).strip()[:500]
        merged["source"] = provider_source
        merged["confidence"] = max(float(local.get("confidence") or 0), 0.86)
        if provider_source == "local_model":
            merged["local_model_provider"] = str(provider.get("_local_model_provider", ""))
            merged["local_model_name"] = str(provider.get("_local_model_name", ""))
    merged["soft_questions"] = unique_strings(merged.get("soft_questions", []), limit=3)
    merged["critical_questions"] = unique_strings(merged.get("critical_questions", []), limit=3)
    merged["missing_required_inputs"] = unique_strings(merged.get("missing_required_inputs", []), limit=6)
    merged["ready_to_generate"] = True
    merged.setdefault("domain_risk_level", "low")
    merged.setdefault("recommended_next_action", "can_start")
    merged.setdefault("start_allowed_with_assumptions", True)
    merged["requires_user_evidence_review"] = bool(merged.get("requires_user_evidence_review", False))
    merged["updated_at"] = now()
    return merged


def update_session_from_analysis(session: dict[str, Any], analysis: dict[str, Any]) -> None:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    whiteboard["project_summary"] = str(analysis.get("project_summary", "")).strip() or str(whiteboard.get("project_summary", "")).strip()
    whiteboard["frontend_plan"] = unique_strings(analysis.get("frontend_plan", []), limit=12)
    whiteboard["backend_plan"] = unique_strings(analysis.get("backend_plan", []), limit=12)
    whiteboard["data_model"] = unique_strings(analysis.get("data_model", []), limit=12)
    whiteboard["required_capabilities"] = unique_strings(analysis.get("required_capabilities", []), limit=12)
    whiteboard["delivery_requirements"] = unique_strings(analysis.get("delivery_requirements", []), limit=12)
    whiteboard["acceptance_criteria"] = unique_strings(analysis.get("acceptance_criteria", []), limit=12)
    whiteboard["known_limits"] = unique_strings(analysis.get("known_limits", []), limit=12)
    whiteboard["missing_config"] = unique_strings(analysis.get("missing_config", []), limit=12)
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
    critical_questions = unique_strings(analysis.get("critical_questions", []), limit=3)
    soft_questions = unique_strings(analysis.get("soft_questions", []), limit=3)
    missing_required_inputs = unique_strings(analysis.get("missing_required_inputs", []), limit=6)
    whiteboard["open_questions"] = unique_strings(critical_questions + soft_questions + missing_required_inputs, limit=8)
    whiteboard["soft_questions"] = unique_strings(analysis.get("soft_questions", []), limit=3)
    whiteboard["critical_questions"] = critical_questions
    whiteboard["missing_required_inputs"] = missing_required_inputs
    whiteboard["domain_risk_level"] = str(analysis.get("domain_risk_level", "low"))
    whiteboard["recommended_next_action"] = str(analysis.get("recommended_next_action", "can_start"))
    if analysis.get("local_image_model_discovery"):
        whiteboard["local_image_model_discovery"] = analysis.get("local_image_model_discovery")
    if analysis.get("capability_strategy"):
        whiteboard["capability_strategy"] = analysis.get("capability_strategy")
    whiteboard["blocking_questions"] = []
    whiteboard["ready_to_generate"] = bool(analysis.get("ready_to_generate", True))
    whiteboard["requires_user_evidence_review"] = bool(analysis.get("requires_user_evidence_review", False))
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
        if str(analysis.get("source", "")) != "local_model":
            budget["api_calls"] = int(budget.get("api_calls") or 0) + 1
        else:
            budget["local_model_calls"] = int(budget.get("local_model_calls") or 0) + 1
        budget["last_model"] = model
        budget["last_api_error"] = provider_error[:500]
    session["backend_dialogue_budget"] = budget
    return analysis
