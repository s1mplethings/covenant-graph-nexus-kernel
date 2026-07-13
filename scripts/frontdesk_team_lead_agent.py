from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


INTERNAL_WORDS = (
    "provider",
    "pipeline",
    "manifest",
    "runner",
    "JSONL",
    "jsonl",
    "BLOCKED",
    "TLS",
    "SSL",
    "SSLError",
    "transport",
    "traceback",
    "exception",
    "stack trace",
)

STATUS_RUNNING = {"queued", "running", "waiting_decision", "waiting_user_review", "revision_generating"}
STATUS_DONE = {"ready", "ready_with_warnings", "delivered", "revision_delivered", "final_delivered"}
STATUS_WAITING = {"waiting_confirmation", "intake_open", "revision_planning"}
STATUS_PAUSED = {"max_turns_reached", "rework_blocked", "blocked", "failed", "error", "generation_blocked_by_local_model_config", "evidence_repair_requested", "needs_repair", "repair_queued", "delivery_send_failed"}


@dataclass(frozen=True)
class TeamLeadReply:
    reply: str
    reply_intent: str
    visible_status: str
    next_user_options: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "reply_intent": self.reply_intent,
            "visible_status": self.visible_status,
            "next_user_options": list(self.next_user_options),
        }


def conversation_history_summary(messages: list[dict[str, Any]] | None, limit: int = 6) -> str:
    if not isinstance(messages, list) or not messages:
        return ""
    lines: list[str] = []
    for item in messages[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip() or "unknown"
        text = str(item.get("text", "")).strip()
        if text:
            lines.append(f"{role}: {text[:220]}")
    return "\n".join(lines)


def known_limits_from_context(
    whiteboard: dict[str, Any] | None,
    generation_status: dict[str, Any] | None,
    delivery_evidence: dict[str, Any] | None,
) -> list[str]:
    out: list[str] = []
    if isinstance(generation_status, dict):
        reason = str(generation_status.get("user_visible_cause") or generation_status.get("error") or "").strip()
        if reason:
            out.append(sanitize_user_visible_error(reason))
    if isinstance(whiteboard, dict):
        for key in ("known_limits", "missing_required_inputs", "unanswered_questions"):
            values = whiteboard.get(key, [])
            if isinstance(values, list):
                out.extend(str(item) for item in values if str(item).strip())
        if whiteboard.get("must_not_claim_full_domain_validation"):
            out.append("存在未确认或未接通的核心能力，不能按完整验收通过来表述。")
    if isinstance(delivery_evidence, dict):
        missing = delivery_evidence.get("missing", [])
        if isinstance(missing, list):
            out.extend(f"缺少{_evidence_label(str(item))}" for item in missing if str(item).strip())
    return _unique(out, limit=12)


def build_context(
    *,
    latest_user_message: str,
    conversation_history_summary: str,
    whiteboard: dict[str, Any],
    active_run: dict[str, Any] | None,
    generation_status: dict[str, Any],
    delivery_evidence: dict[str, Any] | None,
    known_limits: list[str] | None,
    customer_agent_policy: str,
    draft_reply: str = "",
    event: str = "",
) -> dict[str, Any]:
    return {
        "latest_user_message": str(latest_user_message or ""),
        "conversation_history_summary": str(conversation_history_summary or ""),
        "whiteboard": whiteboard if isinstance(whiteboard, dict) else {},
        "active_run": active_run if isinstance(active_run, dict) else {},
        "generation_status": generation_status if isinstance(generation_status, dict) else {},
        "delivery_evidence": delivery_evidence if isinstance(delivery_evidence, dict) else {},
        "known_limits": known_limits if isinstance(known_limits, list) else [],
        "customer_agent_policy": str(customer_agent_policy or ""),
        "draft_reply": str(draft_reply or ""),
        "event": str(event or ""),
    }


def compose_reply(context: dict[str, Any]) -> dict[str, Any]:
    missing = _missing_context_fields(context)
    if missing:
        raise ValueError(f"Team Lead Agent context missing fields: {', '.join(missing)}")

    latest = str(context.get("latest_user_message") or "").strip()
    event = str(context.get("event") or "").strip()
    whiteboard = context.get("whiteboard") if isinstance(context.get("whiteboard"), dict) else {}
    active_run = context.get("active_run") if isinstance(context.get("active_run"), dict) else {}
    generation = context.get("generation_status") if isinstance(context.get("generation_status"), dict) else {}
    evidence = context.get("delivery_evidence") if isinstance(context.get("delivery_evidence"), dict) else {}
    limits = context.get("known_limits") if isinstance(context.get("known_limits"), list) else []
    limits = _unique(
        [str(item) for item in limits if str(item).strip()]
        + known_limits_from_context(whiteboard, generation, evidence),
        limit=12,
    )
    draft = str(context.get("draft_reply") or "").strip()

    intent = _reply_intent(event, latest, generation, evidence)
    visible_status = _visible_status(generation, active_run, evidence)
    options = _next_options(intent, visible_status, evidence, whiteboard)

    if intent == "status":
        reply = _status_reply(latest, visible_status, generation, active_run, evidence, limits, whiteboard)
    elif intent == "greeting":
        reply = _sanitize_public_text(draft) if _draft_is_usable(draft) else _greeting_reply(latest, visible_status, whiteboard)
    elif intent == "correction":
        reply = _correction_reply(latest, visible_status)
    elif intent == "start_generation":
        reply = _start_reply(whiteboard, visible_status)
    elif intent == "delivery_complete":
        reply = _delivery_reply(evidence, limits)
    elif intent == "evidence_missing":
        reply = _evidence_missing_reply(visible_status, evidence, limits, generation)
    elif intent == "change_request":
        reply = _change_request_reply(latest, visible_status)
    else:
        reply = _project_reply(latest, draft, visible_status, whiteboard, limits)

    reply = _avoid_repeated_template(_sanitize_public_text(reply), context)
    return TeamLeadReply(
        reply=reply,
        reply_intent=intent,
        visible_status=visible_status,
        next_user_options=options,
    ).to_dict()


def sanitize_public_text(text: str) -> str:
    return _sanitize_public_text(text)


def is_correction(text: str) -> bool:
    return _is_correction(text)


def sanitize_user_visible_error(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    compact = text.lower()
    if any(term in compact for term in ("tls", "ssl", "bad record mac", "connection reset", "timeout", "timed out", " 502", " 503", " 504", "transport")):
        return "生成服务暂时连接失败，当前不能继续交付。已确认的需求会保留，后续可以从同一上下文继续。"
    if any(term in compact for term in ("quota", "rate limit", "usage limit", "限流", "额度")):
        return "当前生成额度或接口限流，暂时不能继续生成。已确认的需求会保留，后续可以从同一上下文继续。"
    if any(term in compact for term in ("traceback", "exception", "stack trace")):
        return "处理过程被中断，当前不能继续交付。已确认的需求会保留，下一步需要先恢复处理并补齐证据。"
    if any(term in compact for term in ("missing screenshot", "screenshot", "missing video", "video", "missing test report", "test report")):
        return "交付证据还不完整，当前不能算完成。"
    return _strip_internal_error_terms(text) or "处理没有通过检查，当前不能继续交付。"


def _missing_context_fields(context: dict[str, Any]) -> list[str]:
    required = [
        "latest_user_message",
        "conversation_history_summary",
        "whiteboard",
        "active_run",
        "generation_status",
        "delivery_evidence",
        "known_limits",
        "customer_agent_policy",
    ]
    return [key for key in required if key not in context]


def _reply_intent(event: str, latest: str, generation: dict[str, Any], evidence: dict[str, Any]) -> str:
    if event in {"greeting"} or _is_greeting(latest):
        return "greeting"
    if event in {"status_requested"} or _is_status_question(latest):
        return "status"
    if event in {"generation_failed", "project_revision_prepare_failed"}:
        return "evidence_missing"
    if _is_correction(latest):
        return "correction"
    if event in {"generation_started"} or _is_start_message(latest):
        return "start_generation"
    if str(generation.get("status", "")).lower() in STATUS_PAUSED:
        return "evidence_missing"
    if event in {"project_update_running", "project_revision_prepared", "review_revision"} or _is_change_request(latest):
        return "change_request"
    missing = evidence.get("missing", [])
    if event in {"delivery_ready"} or bool(evidence.get("delivery_ready")):
        return "delivery_complete"
    return "project_intake"


def _visible_status(generation: dict[str, Any], active_run: dict[str, Any], evidence: dict[str, Any]) -> str:
    generation_status = str(generation.get("status") or "").lower()
    active_status = str(active_run.get("status") or "").lower()
    if active_status in STATUS_DONE:
        return "交付已整理"
    status = active_status if generation_status in {"", "idle", "none"} and active_status else generation_status or active_status
    if status in STATUS_PAUSED:
        return "需要补证或修复"
    if bool(evidence.get("delivery_ready")) or status in STATUS_DONE:
        return "交付已整理"
    if status in STATUS_RUNNING:
        return "后台正在处理"
    if status in STATUS_WAITING:
        return "等待确认"
    if evidence.get("refs"):
        return "已有部分证据"
    return "尚未开始"


def _next_options(intent: str, visible_status: str, evidence: dict[str, Any], whiteboard: dict[str, Any]) -> list[str]:
    if intent == "status":
        opts = ["继续等当前结果", "补充修改点"]
        missing = evidence.get("missing", [])
        if isinstance(missing, list) and missing:
            opts.append("查看缺失证据")
        return opts[:3]
    if intent == "greeting":
        return ["继续补充需求", "查看当前状态", "换一个新项目"]
    if intent == "start_generation":
        return ["继续补充细节", "等待交付结果"]
    if intent == "delivery_complete":
        return ["查看交付文件", "提出下一版修改", "让我复查某个能力"]
    if intent in {"correction", "change_request"}:
        return ["按这条修正继续", "再补一条修改", "查看当前状态"]
    if whiteboard.get("project_summary"):
        return ["按当前方向开始", "补充验收标准", "调整项目范围"]
    return ["描述项目目标", "上传参考资料"]


def _status_reply(
    latest: str,
    visible_status: str,
    generation: dict[str, Any],
    active_run: dict[str, Any],
    evidence: dict[str, Any],
    limits: list[Any],
    whiteboard: dict[str, Any],
) -> str:
    missing = [_evidence_label(str(item)) for item in evidence.get("missing", []) if str(item).strip()] if isinstance(evidence.get("missing", []), list) else []
    generation_status = str(generation.get("status") or "").strip().lower()
    compact_latest = re.sub(r"[\s,.!?。！？~～]+", "", latest.lower())
    if _is_model_backend_semantics_question(latest):
        return (
            "这里分两层看。第一层是 CGKN 自己生成项目时用什么后端：这轮按当前系统配置继续推进，不会因为目标项目要接本地模型就停住。"
            "第二层是生成出来的项目运行时用什么模型：你的“走本地模型”属于这一层，所以项目里要设计本地模型适配层、模型路径或 endpoint 配置，"
            "并把缺少本地模型文件时不能宣称真实推理通过写进说明和测试限制。"
        )
    if generation_status == "generation_blocked_by_local_model_config" and compact_latest in {"那怎么办", "怎么办", "咋办", "那咋办", "接下来怎么办", "那要怎么办"}:
        return (
            "现在本地模型路线还不能直接开工。如果你愿意改用当前可用生成方式，需要明确说“继续生成”；"
            "在你确认前，我不会替你切换执行方式，也不会新开一轮生成。"
        )
    if any(term in latest for term in ("总结", "做到哪", "到哪了", "现在做到")):
        summary = str(whiteboard.get("project_summary") or "当前项目").strip()
        summary = summary.split("；补充：", 1)[0].strip() or summary
        change_requests = whiteboard.get("change_requests", []) if isinstance(whiteboard.get("change_requests"), list) else []
        lines = [f"现在我这边的判断是：项目目标已经收敛到“{summary[:120]}”。"]
        requested_mode = str(whiteboard.get("requested_generation_mode") or "").strip().lower()
        effective_mode = str(whiteboard.get("effective_generation_mode") or "").strip().lower()
        fallback_explicit = bool(whiteboard.get("local_to_api_fallback_explicit"))
        if requested_mode == "local" and effective_mode == "api" and fallback_explicit:
            lines.append("本地模型路线之前不可用，你已经明确允许这轮改用当前可用生成方式，所以我会沿用同一个项目上下文继续推进。")
        elif requested_mode == "local" and effective_mode == "none":
            lines.append("本地模型路线当前还不可用，也还没有切换到当前可用生成方式。")
        target_architecture = whiteboard.get("target_project_architecture", {}) if isinstance(whiteboard.get("target_project_architecture"), dict) else {}
        cgkn_execution = whiteboard.get("cgkn_execution", {}) if isinstance(whiteboard.get("cgkn_execution"), dict) else {}
        if str(target_architecture.get("model_mode", "")).strip().lower() == "local_model":
            lines.append("生成出来的项目内部会按本地模型路线设计，包含模型适配层、配置入口和缺模型时的限制说明。")
        if str(cgkn_execution.get("generation_backend", "")).strip():
            lines.append("CGKN 这边仍按当前配置的生成后端推进，不把项目内部模型选择和生成执行方式混在一起。")
        change_summary = _public_change_request_summary(change_requests)
        if change_summary:
            lines.append(change_summary)
        if visible_status == "交付已整理":
            lines.append("当前可运行项目、预览图和测试记录已经整理过，可以进入验收或继续提下一版修改。")
            return "".join(lines)
        if missing:
            lines.append("还不能说完成，缺口是：" + "、".join(missing[:4]) + "。")
        lines.append("下一步先补齐这些证据，再判断能不能进入交付。")
        return "".join(lines)
    if "截图" in latest and visible_status == "交付已整理":
        return "截图已经随交付结果整理过了。你可以直接查看刚才发出的效果预览；如果你觉得截图角度或内容不够，我会把它作为下一版补充截图要求处理。"
    if "截图" in latest and any(item in missing for item in ("效果预览", "截图")):
        parts = ["还没有截图，是因为当前还没有拿到可验证的界面预览。"]
        parts.append("现在不能算完成。")
        parts.append("缺的证据是：" + "、".join(missing[:4]) + "。")
        return "".join(parts)
    if visible_status == "后台正在处理":
        parts = ["这轮不是卡死，而是后台正在处理。"]
        parts.append("我这边不会因为这条状态追问开新一轮；新消息只会记录到同一个项目上下文里。")
    elif visible_status == "交付已整理":
        parts = ["进展上看，交付内容已经整理好。"]
        parts.append("已有可交付结果记录，可以继续看结果或提出下一版修改。")
    elif visible_status == "需要补证或修复":
        parts = ["目前还没到交付点。"]
        parts.append("现在不能说完成，因为还有证据或修复项没有闭合。")
    elif active_run:
        parts = [f"进展上看，当前是{visible_status}。"]
        parts.append("已有项目上下文记录，但当前没有正在跑的新任务。")
    else:
        parts = ["目前没有正在跑的后台任务。"]
    if missing and visible_status != "交付已整理":
        parts.append("缺的证据是：" + "、".join(missing[:4]) + "。")
    elif limits:
        parts.append("需要注意：" + "；".join(str(item) for item in limits[:2]) + "。")
    return "".join(parts)


def _public_change_request_summary(change_requests: list[Any]) -> str:
    natural_items = [_naturalize_change_request(item) for item in change_requests[-3:]]
    natural_items = [item for item in natural_items if item]
    if not natural_items:
        return ""
    if len(natural_items) == 1:
        return f"已经纳入的修改重点是：{natural_items[0]}。"
    return "后续修改重点也已经收敛到：" + "；".join(natural_items) + "。"


def _naturalize_change_request(item: Any) -> str:
    text = str(item or "").strip()
    text = re.sub(r"^\s*(?:用户纠正|用户补充|change_request|修改要求)\s*[:：]\s*", "", text, flags=re.I)
    if not text:
        return ""
    if "不是普通代码生成" in text and "项目团队" in text:
        return "你已经明确强调过：这不是普通代码生成，而是要像项目团队一样完成需求确认、生成、测试、截图和交付"
    if "截图" in text and "测试" in text:
        return "先补齐真实截图和测试证据"
    if "机械" in text or "流程" in text or "负责人" in text:
        return "让前台回复更像项目负责人，而不是流程记录"
    return text[:160]


def _greeting_reply(latest: str, visible_status: str, whiteboard: dict[str, Any]) -> str:
    variants = [
        f"我在。当前是{visible_status}，你可以继续补需求、问进度，或者开一个新目标。",
        f"在的。现在这边是{visible_status}；如果要接着推进，直接说下一步要求就行。",
        f"我这边在线。项目这边是{visible_status}。你可以继续补充或让我查进展。",
    ]
    if not str(whiteboard.get("project_summary", "")).strip():
        variants = [
            "我在。你可以直接说想做什么项目，我会先帮你定第一版范围和交付标准。",
            "在的。发一句项目目标就可以，我会把范围、默认假设和验收点一起整理出来。",
            "我这边在线。你直接描述要生成的项目或上传参考资料就行。",
        ]
    return variants[_variant_index(latest or visible_status, len(variants))]


def _correction_reply(latest: str, visible_status: str) -> str:
    correction = latest[:160] or "这条修正"
    return f"收到，按你的说法修正：{correction}。我会把它作为当前项目记忆和后续修改要求处理；这边会按{visible_status}继续衔接。"


def _start_reply(whiteboard: dict[str, Any], visible_status: str) -> str:
    summary = str(whiteboard.get("project_summary") or "").strip()
    requested_mode = str(whiteboard.get("requested_generation_mode") or "").strip().lower()
    effective_mode = str(whiteboard.get("effective_generation_mode") or "").strip().lower()
    target_architecture = whiteboard.get("target_project_architecture", {}) if isinstance(whiteboard.get("target_project_architecture"), dict) else {}
    if requested_mode == "local" and effective_mode == "api":
        target_note = ""
        if str(target_architecture.get("model_mode", "")).strip().lower() == "local_model":
            target_note = " 生成出来的项目仍按本地模型路线设计，我会保留模型适配层、配置入口和缺模型限制说明。"
        if summary:
            return f"可以，你已经明确允许这轮改用当前可用生成方式。{target_note}我会沿用刚才“{summary[:120]}”这个项目上下文继续推进，不另开项目；交付前仍要看真实运行、截图和测试证据。"
        return f"可以，你已经明确允许这轮改用当前可用生成方式。{target_note}我会沿用当前项目上下文继续推进，不另开项目；交付前仍要看真实运行、截图和测试证据。"
    if str(target_architecture.get("model_mode", "")).strip().lower() == "local_model":
        if summary:
            return (
                f"明白，这一版生成出来的项目按本地模型路线设计。我会把模型路径配置、适配层和缺模型时的限制说明写进技术方案；"
                f"CGKN 这边按当前可用的生成后端继续推进“{summary[:120]}”。交付前仍要看可运行项目、截图和测试记录。"
            )
        return (
            "明白，这一版生成出来的项目按本地模型路线设计。我会把模型路径配置、适配层和缺模型时的限制说明写进技术方案；"
            "CGKN 这边按当前可用的生成后端继续推进。交付前仍要看可运行项目、截图和测试记录。"
        )
    if requested_mode == "local" and effective_mode == "local":
        if summary:
            return f"明白，这一版按本地模型路线推进。我会先按“{summary[:120]}”生成第一版；交付前仍要补齐可运行结果、截图和测试记录，缺一项都不能算完成。"
        return "明白，这一版按本地模型路线推进；交付前仍要补齐可运行结果、截图和测试记录，缺一项都不能算完成。"
    if summary:
        return f"收到，我按“{summary[:120]}”这个方向启动第一版。接下来会走项目生成流程，完成后只按真实测试和预览证据交付。"
    return f"收到，我会按当前记录启动第一版。接下来进入{visible_status}，完成前不会把未验证结果说成已交付。"


def _delivery_reply(evidence: dict[str, Any], limits: list[Any]) -> str:
    bits = ["最终交付已经整理好。"]
    refs = evidence.get("refs", {}) if isinstance(evidence.get("refs"), dict) else {}
    if refs:
        labels = [_evidence_label(key) for key in refs.keys()]
        bits.append("目前有：" + "、".join(labels[:4]) + "。")
    bits.append("你可以先验收结果；要改的话直接指出下一版改哪里。")
    if limits:
        bits.append("已知限制：" + "；".join(str(item) for item in limits[:2]) + "。")
    return "".join(bits)


def _evidence_missing_reply(visible_status: str, evidence: dict[str, Any], limits: list[Any], generation: dict[str, Any]) -> str:
    missing = [_evidence_label(str(item)) for item in evidence.get("missing", []) if str(item).strip()] if isinstance(evidence.get("missing", []), list) else []
    if str(generation.get("status") or "").lower() == "generation_blocked_by_local_model_config":
        return (
            "我不能按本地模型路线直接开工，因为当前本地模型能力还没有确认可用。"
            "这个项目需求会保留在同一上下文里；下一步要么先补本地模型配置，要么由你明确允许改用当前可用生成方式。"
        )
    main_limits = _main_public_limits(limits)
    if missing:
        main_limits = [item for item in main_limits if not (item.startswith("缺少") and any(label in item for label in missing))]
    explicit_local_model_block = any("本地模型能力" in str(item) for item in main_limits)
    if (not missing or explicit_local_model_block) and _looks_like_pre_generation_config_gap(main_limits):
        detail_items = [item for item in main_limits[:2] if "本地模型能力还没有确认可用" not in str(item)]
        detail = "；".join(detail_items) or "本地模型路线还没确认可用"
        if "本地模型" in detail:
            return f"我不能直接按本地模型开工，因为当前本地模型能力还没有确认可用。{detail}。我会保留这个项目需求；需要先补本地模型配置，或者你明确允许切换到可用生成方式后再继续。"
        return f"这轮还不该直接开做，关键卡在配置选择上：{detail}。我可以先按可配置入口推进，但不会把未接通的能力说成已经可用。"
    if missing:
        detail = "、".join(missing[:3])
        limit_text = ""
        if main_limits:
            limit_text = "；另外要注意：" + "；".join(main_limits[:1])
        return f"这轮还不能交付。主要缺口是：缺少{detail}{limit_text}。我会保留已确认的需求，先把这些证据补齐，再判断能不能交给你验收。"
    if main_limits:
        return f"现在还不能按完成交付，主要限制是：{'；'.join(main_limits[:3])}。我会先处理这些缺口，再继续推进验收。"
    return "现在还不能按完成交付；需要先补齐可运行结果、预览或测试结论。"


def _change_request_reply(latest: str, visible_status: str) -> str:
    item = latest[:180] or "这条修改"
    if "本地模型" in item and any(token in item for token in ("没有", "缺少", "文件", "配置", "处理")):
        return (
            "这块要诚实处理：项目里可以提供模型路径或 endpoint 配置入口，也可以放 mock adapter 或 dry-run adapter 方便界面和流程先跑通；"
            "但只要没有真实本地模型文件或服务，就不能宣称真实推理通过。README、测试报告和已知限制里都要把这一点写清楚。"
        )
    if "截图" in item or "测试" in item:
        return (
            "对，下一步就先补这两个证据。现在不急着交付，我会先确认项目能跑起来，"
            "再补真实截图和测试结论；这些没补齐之前，这轮不能算完成。"
        )
    if "机械" in item or "模板" in item or "说话" in item:
        return (
            "明白，这不是小问题。前台现在虽然能说明状态，但表达还是偏流程化；"
            "我会把它作为体验修改要求，后续回复少用固定记录口吻，直接说清楚我怎么看、为什么这样处理，以及接下来怎么推进。"
        )
    return f"这会改变这一版的优先级：{item}。我会沿用当前项目继续推进，不另开无关目标；先看它影响哪些验收点，再决定下一步怎么补。"


def _project_reply(latest: str, draft: str, visible_status: str, whiteboard: dict[str, Any], limits: list[Any]) -> str:
    if draft:
        reply = draft
    else:
        summary = str(whiteboard.get("project_summary") or latest or "").strip()
        if any(term in latest for term in ("怎么做第一版", "准备怎么做", "第一版")):
            reply = (
                f"第一版我会先围绕“{summary[:160]}”抓三件事：前台能讲清目标和状态，"
                "中间能暴露截图、测试、交付包这些证据缺口，最后能把修改要求接回同一个项目上下文。"
                "这样先保证交付判断诚实，再继续扩功能。"
            )
        elif summary:
            reply = f"我先按这个方向整理第一版：{summary[:220]}。我会把核心功能、默认假设和验收证据放到同一个项目记录里推进。"
        else:
            reply = "你先把想做的项目目标发来，我会直接整理第一版范围、默认假设和交付标准。"
    if visible_status == "后台正在处理" and "重新" not in reply:
        reply += " 当前后台已经在处理，新补充会并入同一个上下文。"
    if limits and "已知" not in reply and "限制" not in reply:
        reply += " 已知限制会单独记录，不会当成验收通过。"
    return reply


def _sanitize_public_text(text: str) -> str:
    cleaned = sanitize_user_visible_error(text) if _looks_like_internal_error(text) else str(text or "").strip()
    replacements = {
        "API/provider": "外部生成接口",
        "provider": "生成接口",
        "delivery_manifest": "交付清单",
        "pipeline_manifest": "项目执行计划",
        "dynamic_pipeline_runner": "后台执行流程",
        "pipeline": "流程",
        "manifest": "清单",
        "runner": "执行流程",
        "JSONL": "记录文件",
        "jsonl": "记录文件",
        "BLOCKED": "暂停",
        "artifact": "证据",
        "Artifact": "证据",
        "agent_session": "工作记录",
        "whiteboard": "项目记录",
        "local_packager": "交付整理",
        "虚拟项目组": "项目生成流程",
        "客服": "前台沟通",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = _remove_public_structure_labels(cleaned)
    cleaned = re.sub(r"\b[a-zA-Z0-9_-]*_blocked\.json\b", "缺失记录", cleaned)
    cleaned = re.sub(r"[A-Za-z]:\\[^\s，。；]+", "本地工作区记录", cleaned)
    cleaned = re.sub(r"\b(?:provider|pipeline|manifest|runner|JSONL|jsonl|BLOCKED|TLS|SSL|SSLError|transport|traceback|exception|stack trace)\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned[:3900] or "这条消息已记录，我会按当前项目上下文继续处理。"


def _looks_like_internal_error(raw: Any) -> bool:
    compact = str(raw or "").lower()
    return any(
        term in compact
        for term in (
            "tls",
            "ssl",
            "bad record mac",
            "connection reset",
            "transport",
            "traceback",
            "exception",
            "stack trace",
            "provider",
            "quota",
            "rate limit",
        )
    )


def _strip_internal_error_terms(text: str) -> str:
    cleaned = re.sub(
        r"\b(?:provider|pipeline|manifest|runner|JSONL|jsonl|BLOCKED|TLS|SSL|SSLError|transport|traceback|exception|stack trace)\b",
        "",
        str(text or ""),
        flags=re.I,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" :;，。")
    return cleaned


def _draft_is_usable(draft: str) -> bool:
    if not str(draft or "").strip():
        return False
    lowered = str(draft).lower()
    generic_fallbacks = (
        "当前项目上下文已记录",
        "当前消息已记录",
        "这条消息已记录",
        "我会按最新目标继续处理",
    )
    if any(phrase in str(draft) for phrase in generic_fallbacks):
        return False
    return not any(term.lower() in lowered for term in INTERNAL_WORDS)


def _avoid_repeated_template(reply: str, context: dict[str, Any]) -> str:
    history = str(context.get("conversation_history_summary") or "")
    last_assistant = ""
    for line in reversed(history.splitlines()):
        if line.startswith("assistant:"):
            last_assistant = line.split(":", 1)[1].strip()
            break
    if not last_assistant:
        return reply
    current_head = _head_signature(reply)
    last_head = _head_signature(last_assistant)
    if current_head and current_head == last_head:
        if reply.startswith("收到，"):
            return "这条我记下了，" + reply[len("收到，") :]
        if reply.startswith("我在。"):
            return "在的。" + reply[len("我在。") :]
        if reply.startswith("当前状态："):
            return "状态这边看是：" + reply[len("当前状态：") :]
    return reply


def _head_signature(text: str) -> str:
    compact = re.sub(r"[\s，。,.!?！？；;：:]+", "", text)
    return compact[:12]


def _evidence_label(raw: str) -> str:
    key = raw.lower()
    mapping = {
        "package": "可运行项目文件",
        "screenshot": "效果预览",
        "verify_report": "测试结论",
        "verify_passed": "测试通过记录",
        "delivery_manifest": "交付清单",
        "final_project_bundle": "最终项目包",
    }
    for marker, label in mapping.items():
        if marker in key:
            return label
    return raw.replace("_", " ")


def _is_greeting(text: str) -> bool:
    compact = re.sub(r"[\s，。,.!?！？~～]+", "", text.lower())
    return compact in {"你好", "您好", "在吗", "hi", "hello", "hey"}


def _is_status_question(text: str) -> bool:
    compact = re.sub(r"[\s，。,.!?！？~～]+", "", text.lower())
    if _is_model_backend_semantics_question(text):
        return True
    return compact in {"状态", "进度", "好了没", "还在做吗", "还在跑吗", "status"} or (
        any(x in compact for x in ("状态", "进度", "还在", "好了", "结果", "动静"))
        and any(x in compact for x in ("吗", "没", "怎样", "怎么样", "到哪", "有"))
    )


def _is_model_backend_semantics_question(text: str) -> bool:
    compact = re.sub(r"[\s，。,.!?！？~～+＋]+", "", str(text or "").lower())
    has_model_word = "本地模型" in compact or "localmodel" in compact
    has_generation_word = any(word in compact for word in ("生成", "做", "执行", "跑"))
    has_backend_choice = "api" in compact or "接口" in compact or "后端" in compact
    return has_model_word and has_backend_choice and has_generation_word and any(word in compact for word in ("还是", "用api", "用接口", "本地模型生成"))


def _is_start_message(text: str) -> bool:
    compact = re.sub(r"[\s，。,.!?！？~～+＋]+", "", text.lower())
    return any(term in compact for term in ("开始生成", "按默认", "启动生成", "开工", "生成吧", "开始做", "开始吧", "做吧", "直接做", "走本地模型开始做吧"))


def _is_correction(text: str) -> bool:
    return any(term in text for term in ("不是", "不对", "纠正", "我要的是", "应该是", "改成"))


def _is_change_request(text: str) -> bool:
    evidence_repair = any(term in text for term in ("补", "补齐", "先补")) and any(term in text for term in ("截图", "测试", "证据", "预览", "交付包"))
    expression_repair = any(term in text for term in ("机械", "模板", "客服", "流程播报", "不像负责人"))
    return any(term in text for term in ("修改", "加上", "去掉", "必须", "不要", "后续", "调整")) or evidence_repair or expression_repair


def _variant_index(seed: str, modulo: int) -> int:
    digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:8], 16) % max(1, modulo)


def _unique(values: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _remove_public_structure_labels(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"(?m)^\s*(?:判断|原因|下一步)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(r"(?m)([。！？\n])\s*(?:判断|原因|下一步)\s*[:：]\s*", r"\1", cleaned)
    cleaned = cleaned.replace("当前状态是", "现在这边是")
    cleaned = cleaned.replace("状态是", "这边是")
    return cleaned


def _main_public_limits(limits: list[Any]) -> list[str]:
    out: list[str] = []
    for item in limits:
        text = str(item or "").strip()
        if not text:
            continue
        text = text.rstrip("。；;")
        if "最近停在" in text:
            continue
        if len(text) > 90:
            text = text[:90]
        if text not in out:
            out.append(text)
        if len(out) >= 3:
            break
    return out


def _looks_like_pre_generation_config_gap(items: list[Any]) -> bool:
    text = "\n".join(str(item or "") for item in items)
    return any(term in text for term in ("未配置", "模型路径", "本地模型", "接口地址", "API key", "外部服务配置"))
