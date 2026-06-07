#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re
from typing import Any

import local_image_model_discovery


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def _unique(values: list[Any], limit: int = 20) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out[:limit]


def _priority(text: str, capability_id: str) -> str:
    explicit = _contains_any(text, ("必须", "一定要", "核心", "关键", "我要的是", "不能", "不允许", "真实", "正经", "直接"))
    if explicit:
        return "critical"
    if capability_id in {"content_generation", "local_model_backend", "runtime_preview", "local_persistence"}:
        return "high"
    return "normal"


def infer_capabilities(text: str) -> list[dict[str, Any]]:
    raw = str(text or "")
    capabilities: list[dict[str, Any]] = []

    def add(capability_id: str, label: str, reason: str) -> None:
        if not any(item["id"] == capability_id for item in capabilities):
            capabilities.append({"id": capability_id, "label": label, "priority": _priority(raw, capability_id), "reason": reason})

    if _contains_any(raw, ("流程", "时间线", "关系", "图谱", "依赖", "状态流", "story", "timeline", "workflow", "graph")):
        add("structured_workflow_modeling", "结构化流程/关系建模", "用户要求的不只是普通文本输出，而是带结构、顺序、依赖或关系的核心工作流。")
    if _contains_any(raw, ("生成", "创作", "生成图", "生成图片", "生成视频", "生成音频", "生成文本", "生成代码", "生成报告", "image generation", "video generation", "content generation")):
        add("content_generation", "内容生成能力", "用户要求系统直接产出内容，生成质量、模型/API 和验收证据会决定项目是否成立。")
    if _contains_any(raw, ("本地图片模型", "本地的图片模型", "本地模型", "本地生图", "stable diffusion", "comfyui", "automatic1111", "a1111", "sdxl", "flux")):
        add("local_model_backend", "本地模型后端", "用户指定了本地模型能力，模型配置本身会影响能否验收。")
    if _contains_any(raw, ("预览", "截图", "视频", "mp4", "测试效果", "实际测试", "可视化")):
        add("runtime_preview", "真实运行预览和证据", "用户要看效果，必须生成可检查的图片/截图/视频/测试报告。")
    if _contains_any(raw, ("上传", "导入", "导出", "excel", "csv", "pdf", "图片", "文件", "附件", "格式", "download", "upload", "export", "import")):
        add("import_export_interop", "导入导出和格式互操作", "用户要求文件、格式、上传下载或外部数据交换，格式兼容性会直接影响可用性。")
    if _contains_any(raw, ("识别", "提取", "抽取", "ocr", "字段", "解析", "分类", "审核", "检测", "匹配", "extract", "parse", "recognize", "classify")):
        add("data_extraction_understanding", "数据抽取和理解", "用户要求系统从资料或输入中提取结构化信息，需要成熟解析、模型或校验策略。")
    if _contains_any(raw, ("自动化", "自动执行", "定时", "抓取", "监控", "提醒", "通知", "异常", "爬虫", "调度", "后台任务", "scheduler", "scrape", "crawl", "monitor", "alert", "notify")):
        add("automation_execution", "自动化执行和调度", "用户要求系统主动执行、监控或提醒，需要调度、重试、异常处理和证据记录。")
    if _contains_any(raw, ("队列", "失败重试", "重试", "异步", "批处理", "worker", "queue", "retry", "async")):
        add("job_queue_reliability", "任务队列和可靠执行", "用户要求队列、异步、重试或批处理，可靠性和状态追踪会影响真实可用性。")
    if _contains_any(raw, ("实时", "传感器", "流数据", "websocket", "stream", "realtime", "sensor", "mqtt")):
        add("realtime_streaming", "实时数据接入和流式状态", "用户要求实时数据或设备流，必须处理连接、刷新、延迟和异常状态。")
    if _contains_any(raw, ("预测", "趋势", "风险", "评分", "建议", "推荐", "缺货", "异常交易", "forecast", "predict", "risk", "recommend")):
        add("analytics_prediction_decisioning", "分析预测和决策建议", "用户要求预测、风险、趋势或建议，必须有数据样例、指标和可解释输出。")
    if _contains_any(raw, ("证据链", "审计", "复核", "版本对比", "决策日志", "人工确认", "人工复核", "audit", "review", "evidence", "version")):
        add("audit_review_traceability", "审计、复核和证据链", "用户要求可追溯、人工复核或版本证据，交付必须保留决策和变更记录。")
    if _contains_any(raw, ("权限", "隐私", "不能发到云端", "不能出本机", "本地资料", "安全", "审批", "报销", "审核", "多角色", "角色", "credential", "secret", "privacy", "permission", "role")):
        add("security_control", "安全、权限和数据边界", "用户或场景涉及隐私、审批、凭据或权限，边界选择会影响方案和验收。")
    if _contains_any(raw, ("知识库", "向量", "搜索", "检索", "问答", "embedding", "vector", "retrieval", "rag", "search")):
        add("retrieval_search", "检索、搜索和知识库", "用户要求查找、问答或知识库能力，需要索引、检索质量和数据更新策略。")
    if _contains_any(raw, ("保存", "数据库", "历史", "记忆", "状态", "后台", "持久化")):
        add("local_persistence", "本地状态和数据持久化", "后台状态、历史和生成记录需要可恢复的存储策略。")
    if _contains_any(raw, ("agent", "多角色", "cfo", "模块", "管线")):
        add("agent_orchestration", "多角色 agent 编排", "用户关心底层 agent 分工和模块管线，而不是单文件工具。")
    if _contains_any(raw, ("网页", "web", "前端", "界面", "gui", "桌面", "移动端", "手机端", "mobile")):
        add("product_ui", "产品界面和交互", "用户需要实际操作界面，交互形态影响项目结构和测试。")

    return capabilities[:10]


def advanced_methods_for(capability: dict[str, Any], text: str, project_root: pathlib.Path | None) -> list[dict[str, str]]:
    capability_id = str(capability.get("id", ""))
    if capability_id in {"content_generation", "local_model_backend"}:
        questions, discovery = local_image_model_discovery.critical_questions_for_text(text, project_root)
        explicit_image_local = local_image_model_discovery.requests_local_image_model(text)
        local_status = "available" if discovery.get("available") else ("missing" if explicit_image_local else "needs_capability_probe")
        return [
            {
                "name": "Configured local model/service backend",
                "fit": "适合用户要求本地、隐私、成本或离线能力的生成任务；需要探测模型服务、模型目录、运行资源和能力范围。",
                "requirement_status": local_status,
            },
            {
                "name": "Hosted provider/API backend",
                "fit": "适合本地能力不足但用户允许外部服务的高质量生成任务；必须做凭据/能力探测，不能静默假设可用。",
                "requirement_status": "candidate",
            },
            {
                "name": "Domain-specialized engine or library",
                "fit": "适合有成熟专用引擎的生成任务；应先找库/模型/API，再决定是否自研。",
                "requirement_status": "candidate",
            },
            {
                "name": "Explicit fallback implementation",
                "fit": "只能作为降级预览、接口演示或离线占位；不能冒充用户要求的高级生成能力。",
                "requirement_status": local_status,
            },
        ]
    if capability_id == "structured_workflow_modeling":
        return [
            {"name": "graph/state-machine model", "fit": "适合时间线、依赖、状态流、分支、审批、任务流等结构化关系。", "requirement_status": "candidate"},
            {"name": "table + relation index", "fit": "适合第一版快速落地，明确实体、关系、顺序和冲突检查。", "requirement_status": "candidate"},
        ]
    if capability_id == "runtime_preview":
        return [
            {"name": "browser automation evidence", "fit": "用真实运行截图、生成图片和短视频验证，而不是只写 README。", "requirement_status": "candidate"},
            {"name": "artifact manifest verification", "fit": "把图片/视频/测试报告写入交付清单，缺失时标记 warning/fail。", "requirement_status": "candidate"},
        ]
    if capability_id == "import_export_interop":
        return [
            {"name": "schema-first file adapters", "fit": "先定义输入/输出 schema，再接 PDF、图片、CSV、Excel、JSON 等适配器。", "requirement_status": "candidate"},
            {"name": "format validation and sample fixtures", "fit": "用真实样例文件和导出校验防止只做界面不做格式兼容。", "requirement_status": "candidate"},
        ]
    if capability_id == "data_extraction_understanding":
        return [
            {"name": "specialized parser/OCR/model pipeline", "fit": "适合字段抽取、OCR、分类、审核、检测等任务；先找成熟解析器/模型/API，再决定 fallback。", "requirement_status": "candidate"},
            {"name": "confidence + human review workflow", "fit": "对识别错误敏感的场景，应保留置信度、人工确认和修正记录。", "requirement_status": "candidate"},
        ]
    if capability_id == "automation_execution":
        return [
            {"name": "scheduler + retry + run log", "fit": "适合定时抓取、监控、提醒、后台任务；需要失败重试和运行证据。", "requirement_status": "candidate"},
            {"name": "event-driven worker queue", "fit": "适合任务量较大或异步处理，能把执行和 UI 状态分开。", "requirement_status": "candidate"},
        ]
    if capability_id == "job_queue_reliability":
        return [
            {"name": "durable job queue + status store", "fit": "适合上传处理、批量生成、视频处理、失败重试和后台 worker。", "requirement_status": "candidate"},
            {"name": "idempotent retry and dead-letter handling", "fit": "适合不能静默丢任务的流程，记录失败原因和可重跑入口。", "requirement_status": "candidate"},
        ]
    if capability_id == "realtime_streaming":
        return [
            {"name": "stream ingestion + live state cache", "fit": "适合传感器、设备、行情、监控数据，分离接入、缓存、告警和 UI 刷新。", "requirement_status": "candidate"},
            {"name": "polling fallback with freshness indicators", "fit": "实时服务不可用时保留可测的轮询降级，但必须显示数据新鲜度。", "requirement_status": "candidate"},
        ]
    if capability_id == "analytics_prediction_decisioning":
        return [
            {"name": "baseline analytics + model-ready feature pipeline", "fit": "先用可解释指标和样例数据验证预测/风险建议，再接高级模型。", "requirement_status": "candidate"},
            {"name": "forecast/risk scoring model adapter", "fit": "适合库存预测、异常检测、趋势预测和推荐建议；需要评估样例和置信度。", "requirement_status": "candidate"},
        ]
    if capability_id == "audit_review_traceability":
        return [
            {"name": "audit trail + review workflow", "fit": "记录输入、模型/规则判断、人工确认、版本和导出证据。", "requirement_status": "candidate"},
            {"name": "diff/version evidence model", "fit": "适合文档审查、审批、风控、报告修订和证据链场景。", "requirement_status": "candidate"},
        ]
    if capability_id == "security_control":
        return [
            {"name": "local/private data boundary", "fit": "适合不能上传云端、涉及凭据或审批的项目；需要明确哪些数据可离开本机。", "requirement_status": "candidate"},
            {"name": "role/approval policy", "fit": "适合审核、报销、权限和高风险操作；需要权限和确认流程。", "requirement_status": "candidate"},
        ]
    if capability_id == "retrieval_search":
        return [
            {"name": "local vector store + embedding pipeline", "fit": "适合本地知识库、RAG、语义搜索；需要索引更新和命中质量测试。", "requirement_status": "candidate"},
            {"name": "hybrid keyword + semantic search", "fit": "适合准确性要求高的检索，减少单一路线漏召回。", "requirement_status": "candidate"},
        ]
    if capability_id == "local_persistence":
        return [
            {"name": "SQLite for structured state", "fit": "适合项目、任务、生成记录、素材索引和状态恢复。", "requirement_status": "candidate"},
            {"name": "JSON store for first version", "fit": "适合小型本地 demo，但并发和查询能力较弱。", "requirement_status": "basic_candidate"},
        ]
    if capability_id == "agent_orchestration":
        return [
            {"name": "CFO-controlled module pipeline", "fit": "一个主 agent 负责模块计划、验收和交付准备，支援 agent 只维护上下文/风险。", "requirement_status": "candidate"},
            {"name": "support context database + risk register", "fit": "把需求、决策、关键差异和验收风险显式交给后续 worker。", "requirement_status": "candidate"},
        ]
    return [{"name": "specialist implementation research", "fit": "该能力需要在 CFO 计划中先找成熟库/模型/API，再决定实现。", "requirement_status": "candidate"}]


def decision_points_for(text: str, capabilities: list[dict[str, Any]], local_image_questions: list[str], local_image_available: bool) -> list[str]:
    ids = {str(item.get("id", "")) for item in capabilities}
    points: list[str] = []
    if "local_model_backend" in ids:
        points.extend(local_image_questions)
        if not local_image_available:
            points.append("如果指定的本地模型/服务暂时不可用，要不要允许外部高级 API/模型作为临时备选，还是严格只接受本地能力？")
    elif "content_generation" in ids:
        points.append("生成能力优先走本地模型、外部高级 API，还是两者都做成可配置？")
    if "structured_workflow_modeling" in ids and _contains_any(text, ("分支", "多结局", "选择支", "branch", "审批", "状态")):
        points.append("结构化流程第一版做线性/表格关系，还是直接支持分支、状态机或图结构？")
    if "local_persistence" in ids and not _contains_any(text, ("sqlite", "数据库", "json")):
        points.append("本地状态第一版用 SQLite 结构化保存，还是用简单 JSON 文件保存？")
    if "data_extraction_understanding" in ids:
        points.append("数据抽取/识别结果需要自动通过，还是必须带置信度和人工确认流程？")
    if "automation_execution" in ids:
        points.append("自动化任务第一版需要定时后台运行，还是先做手动触发加运行日志？")
    if "job_queue_reliability" in ids:
        points.append("后台任务需要持久队列和失败重试，还是第一版只做单机同步处理？")
    if "realtime_streaming" in ids:
        points.append("实时数据要用持续连接/流式接入，还是第一版允许轮询刷新并显示数据新鲜度？")
    if "analytics_prediction_decisioning" in ids:
        points.append("预测/建议第一版要可解释规则基线，还是直接接入模型评分并给置信度？")
    if "audit_review_traceability" in ids:
        points.append("高风险结果需要人工复核和证据链，还是允许系统自动通过并仅记录日志？")
    if "security_control" in ids:
        points.append("涉及资料和凭据时，是否要求严格本地处理，还是允许配置外部服务？")
    if "retrieval_search" in ids:
        points.append("检索/问答优先用本地向量库，外部向量服务，还是两者可配置？")
    if "product_ui" in ids and _contains_any(text, ("桌面", "网页", "gui")) and not _contains_any(text, ("只要网页", "只要桌面")):
        points.append("第一版运行形态要本地网页，还是桌面窗口？这会影响打包和测试方式。")
    return _unique(points, limit=4)


def build_capability_strategy(text: str, project_root: str | pathlib.Path | None = None) -> dict[str, Any]:
    root = pathlib.Path(project_root) if project_root else None
    capabilities = infer_capabilities(text)
    local_questions, local_discovery = local_image_model_discovery.critical_questions_for_text(text, root)
    research_targets: list[dict[str, Any]] = []
    for capability in capabilities:
        research_targets.append(
            {
                "capability": capability,
                "advanced_methods": advanced_methods_for(capability, text, root),
            }
        )
    decision_points = decision_points_for(text, capabilities, local_questions, bool(local_discovery.get("available")))
    acceptance: list[str] = []
    if any(item.get("id") in {"content_generation", "local_model_backend"} for item in capabilities):
        acceptance.append("生成类核心能力必须有明确模型/API/本地后端/专用引擎能力检查；占位或降级预览不能冒充真实生成。")
    if "local_model_backend" in {str(item.get("id", "")) for item in capabilities}:
        acceptance.append("用户要求本地模型时，外部模型只能作为备选说明，不能算满足本地模型验收。")
    if any(item.get("id") == "runtime_preview" for item in capabilities):
        acceptance.append("交付必须包含真实运行证据：截图、生成图片、视频或测试报告中至少按用户要求提供。")
    if any(item.get("id") == "data_extraction_understanding" for item in capabilities):
        acceptance.append("数据抽取/识别能力必须用样例输入验证字段、置信度或错误处理，不能只做空表单。")
    if any(item.get("id") == "automation_execution" for item in capabilities):
        acceptance.append("自动化能力必须有触发方式、运行日志、失败提示或重试策略，不能只写静态配置。")
    if any(item.get("id") == "job_queue_reliability" for item in capabilities):
        acceptance.append("队列/异步任务必须有状态、失败原因和重试或重跑入口，不能只做一次性同步调用。")
    if any(item.get("id") == "realtime_streaming" for item in capabilities):
        acceptance.append("实时能力必须显示数据新鲜度、连接状态和异常状态，不能用静态样例冒充实时接入。")
    if any(item.get("id") == "analytics_prediction_decisioning" for item in capabilities):
        acceptance.append("预测/风险/建议能力必须用样例数据给出指标、理由或置信度，不能只输出固定文案。")
    if any(item.get("id") == "audit_review_traceability" for item in capabilities):
        acceptance.append("审计/复核/证据链能力必须保存输入、判断、人工操作和版本记录。")
    if any(item.get("id") == "security_control" for item in capabilities):
        acceptance.append("涉及隐私、凭据或权限时，交付必须明确数据边界和不可静默外传的规则。")

    return {
        "kind": "CapabilityStrategy",
        "capabilities": capabilities,
        "research_targets": research_targets,
        "critical_questions": decision_points,
        "acceptance_criteria": _unique(acceptance, limit=8),
        "local_image_model_discovery": local_discovery,
        "decision_log": [
            "先识别用户显式/隐式核心能力，再为核心能力寻找成熟模型、库、API 或本地后端；明显影响产品效果的路线差异必须向用户确认。"
        ],
    }
