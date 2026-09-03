#!/usr/bin/env python3
"""Codex conversation product-design intake and bounded Codex advisory handoff.

This adapter owns no generation, evidence, packaging, or delivery authority.  It
only turns an explicit interface request into whiteboard support state and the
existing CGKNCodexCapabilityEscalation/Brief contract.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
from typing import Any

import codex_capability_supervisor


ROOT = pathlib.Path(__file__).resolve().parents[1]
DRAFT_SCHEMA = (
    ROOT
    / "tools"
    / "cgkn-agent-kit"
    / "src"
    / "cgkn_agent_kit"
    / "schemas"
    / "supervisor_draft.schema.json"
)

DESIGN_STATE_KEY = "product_design"
DESIGN_WORKFLOW_PENDING = {
    "awaiting_codex_brief",
    "codex_running",
    "codex_unavailable",
    "awaiting_user_confirmation",
}

_SURFACE_TERMS = (
    "gui",
    "ui",
    "ux",
    "界面",
    "页面",
    "前端",
    "网页",
    "web app",
    "webapp",
    "控制台",
    "看板",
    "仪表盘",
    "交互设计",
    "产品设计",
    "移动端",
    "手机端",
)
_CODEX_TERMS = ("codex", "对话", "conversation")
_REDESIGN_TERMS = (
    "为什么没有",
    "怎么没有",
    "设计很差",
    "重新设计",
    "重做界面",
    "不要命令行",
    "不只是命令行",
    "没有gui",
    "没有界面",
)
_CONFIRM_TERMS = (
    "设计确认",
    "确认设计",
    "界面确认",
    "这个设计可以",
    "按这个界面",
    "按这个设计",
    "设计没问题",
)

DEFAULT_ACCEPTANCE = [
    "Codex 对话负责需求、确认、状态说明、结果展示和后续修改",
    "生成项目自己的界面必须遵循目标设备布局、明暗主题、键盘操作和可访问标签要求",
    "每个操作保持一个明确功能、明确输入和明确输出；多个独立功能通过统一动作接口并行组合",
    "交付前必须提供真实可操作页面的手机尺寸明暗主题截图和一段关键流程演示视频",
]
DEFAULT_PLAN = [
    "Codex 对话：自然语言需求、设计确认、进度说明、结果展示和继续修改",
    "项目界面：首页总览、单功能操作页、任务/结果页和设置页",
    "共享动作契约：每个功能声明名称、输入、输出、错误和副作用，独立功能可并行构建",
]


def _unique(values: list[Any], limit: int = 120) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result[-limit:]


def _compact(text: str) -> str:
    return re.sub(r"[\s，。,.!?！？~～:_-]+", "", str(text or "").lower())


def _contains_term(lowered: str, compact: str, term: str) -> bool:
    normalized = str(term or "").lower()
    if normalized.isascii() and normalized.replace(" ", "").isalnum():
        collapsed = normalized.replace(" ", "")
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(collapsed)}(?![a-z0-9])", compact))
    return normalized in lowered or _compact(normalized) in compact


def _sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_json(path: pathlib.Path, value: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    )
    temporary = pathlib.Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _safe_conversation_id(conversation_id: int | str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(conversation_id or "chat"))[:120] or "chat"


def design_intent_from_text(text: str, whiteboard: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect product-interface intent without treating media-only requests as GUI work."""
    raw = str(text or "").strip()
    lowered = raw.lower()
    compact = _compact(raw)
    existing = whiteboard if isinstance(whiteboard, dict) else {}
    current = existing.get(DESIGN_STATE_KEY, {}) if isinstance(existing.get(DESIGN_STATE_KEY), dict) else {}
    confirmation = bool(current.get("required")) and any(_compact(term) in compact for term in _CONFIRM_TERMS)
    redesign = any(_compact(term) in compact for term in _REDESIGN_TERMS)
    has_surface = any(_contains_term(lowered, compact, term) for term in _SURFACE_TERMS)
    media_only = (
        any(term in lowered for term in ("图片", "截图", "视频", "预览", "image", "video", "screenshot"))
        and not has_surface
        and not redesign
    )
    required = bool((has_surface or redesign) and not media_only)
    codex = any(_contains_term(lowered, compact, term) for term in _CODEX_TERMS)
    surfaces: list[str] = []
    if required:
        if codex or str(existing.get("source", "")).lower() == "codex":
            surfaces.append("codex_conversation")
        elif any(term in lowered for term in ("桌面", "desktop")):
            surfaces.append("desktop_app")
        else:
            surfaces.append("generated_project_ui")
    return {
        "required": required,
        "confirmation": confirmation,
        "redesign": redesign,
        "interaction_surfaces": surfaces,
        "reason": "user_requested_interface_redesign" if redesign else "user_requested_product_interface",
    }


def apply_design_intent(whiteboard: dict[str, Any], text: str, *, codex_default: bool = True) -> dict[str, Any]:
    """Apply deterministic design support state; never starts generation."""
    result = dict(whiteboard if isinstance(whiteboard, dict) else {})
    current = result.get(DESIGN_STATE_KEY, {}) if isinstance(result.get(DESIGN_STATE_KEY), dict) else {}
    intent = design_intent_from_text(text, result)
    if intent["confirmation"] and current.get("workflow_state") == "awaiting_user_confirmation":
        result[DESIGN_STATE_KEY] = {
            **current,
            "workflow_state": "approved",
            "user_confirmed": True,
            "confirmation_text": str(text or "")[:500],
        }
        result["decision_log"] = _unique(
            list(result.get("decision_log", []) if isinstance(result.get("decision_log"), list) else [])
            + ["用户已确认当前交互与界面设计，可以进入正式生成。"]
        )
        return result
    if not intent["required"]:
        return result

    surfaces = list(intent["interaction_surfaces"])
    if codex_default and not surfaces:
        surfaces = ["codex_conversation"]
    if codex_default and surfaces == ["generated_project_ui"]:
        surfaces = ["codex_conversation", "generated_project_ui"]
    prior_surfaces = current.get("interaction_surfaces", []) if isinstance(current.get("interaction_surfaces"), list) else []
    workflow_state = "awaiting_codex_brief"
    result[DESIGN_STATE_KEY] = {
        **current,
        "required": True,
        "workflow_state": workflow_state,
        "interaction_surfaces": _unique(prior_surfaces + surfaces, limit=8),
        "reason": intent["reason"],
        "latest_request": str(text or "")[:1200],
        "user_confirmation_required": True,
        "user_confirmed": False,
        "advisory_only": True,
    }
    result["first_version_plan"] = _unique(
        list(result.get("first_version_plan", []) if isinstance(result.get("first_version_plan"), list) else [])
        + DEFAULT_PLAN
    )
    result["acceptance_criteria"] = _unique(
        list(result.get("acceptance_criteria", []) if isinstance(result.get("acceptance_criteria"), list) else [])
        + DEFAULT_ACCEPTANCE
    )
    result["delivery_requirements"] = _unique(
        list(result.get("delivery_requirements", []) if isinstance(result.get("delivery_requirements"), list) else [])
        + ["交付时直接发送手机尺寸明暗主题界面截图和关键流程演示视频"]
    )
    result["decision_log"] = _unique(
        list(result.get("decision_log", []) if isinstance(result.get("decision_log"), list) else [])
        + ["界面型项目先完成交互设计并由用户确认，再进入正式生成；业务功能仍保持单一职责和统一动作接口。"]
    )
    if intent["redesign"]:
        result["change_requests"] = _unique(
            list(result.get("change_requests", []) if isinstance(result.get("change_requests"), list) else [])
            + [str(text or "")]
        )
    result["ready_to_generate"] = False
    return result


def design_supervision_pending(whiteboard: dict[str, Any] | None) -> bool:
    board = whiteboard if isinstance(whiteboard, dict) else {}
    state = board.get(DESIGN_STATE_KEY, {}) if isinstance(board.get(DESIGN_STATE_KEY), dict) else {}
    return bool(state.get("required")) and str(state.get("workflow_state", "")) != "approved"


def apply_api_only_design_baseline(whiteboard: dict[str, Any]) -> dict[str, Any]:
    """Prepare the existing design-confirmation checkpoint without invoking Codex."""
    result = dict(whiteboard if isinstance(whiteboard, dict) else {})
    state = result.get(DESIGN_STATE_KEY, {}) if isinstance(result.get(DESIGN_STATE_KEY), dict) else {}
    if not state.get("required") or state.get("workflow_state") == "approved":
        return result
    surfaces = state.get("interaction_surfaces", []) if isinstance(state.get("interaction_surfaces"), list) else []
    surface_text = "、".join(str(item) for item in surfaces if str(item).strip()) or "用户界面"
    result[DESIGN_STATE_KEY] = {
        **state,
        "workflow_state": "awaiting_user_confirmation",
        "brief_summary": f"{surface_text}采用当前需求中已冻结的页面、交互、响应式和可访问性要求。",
        "design_source": "api_only_baseline",
        "codex_used": False,
        "advisory_only": True,
    }
    result["decision_log"] = _unique(
        list(result.get("decision_log", []) if isinstance(result.get("decision_log"), list) else [])
        + ["API-only 模式不调用 Codex；界面基础方案仍需用户确认后才能进入正式 Provider 生成。"]
    )
    result["ready_to_generate"] = False
    return result


def design_support_dir(session_dir: pathlib.Path, conversation_id: int | str) -> pathlib.Path:
    return pathlib.Path(session_dir) / _safe_conversation_id(conversation_id) / "design_supervision"


def _selected_context(whiteboard: dict[str, Any], latest_text: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for key in (
        "project_summary",
        "known_facts",
        "user_rules",
        "change_requests",
        "first_version_plan",
        "acceptance_criteria",
        "delivery_requirements",
    ):
        value = whiteboard.get(key)
        if value in (None, "", []):
            continue
        items.append({
            "id": f"codex-{key}",
            "kind": "codex_whiteboard_selection",
            "path": key,
            "summary": json.dumps(value, ensure_ascii=False)[:1400],
        })
    if latest_text:
        items.insert(0, {
            "id": "codex-latest-request",
            "kind": "codex_user_request",
            "path": "latest_user_text",
            "summary": latest_text[:1400],
        })
    return {
        "kind": "CGKNLibrarianContextPack",
        "selected_items": items[:8],
        "excluded_count": max(0, len(items) - 8),
        "bounded": True,
    }


def prepare_design_escalation(
    session_dir: pathlib.Path,
    conversation_id: int | str,
    session: dict[str, Any],
    agent_session: pathlib.Path,
) -> dict[str, Any]:
    """Create or reuse one bounded request and update the caller-owned session."""
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    state = whiteboard.get(DESIGN_STATE_KEY, {}) if isinstance(whiteboard.get(DESIGN_STATE_KEY), dict) else {}
    if not state.get("required"):
        return {"status": "not_required"}
    latest_text = str(state.get("latest_request", "") or "")
    goal = str(whiteboard.get("project_summary", "") or latest_text or "Codex conversation interface project")[:2000]
    fingerprint = _sha256({
        "goal": goal,
        "latest_request": latest_text,
        "surfaces": state.get("interaction_surfaces", []),
        "acceptance": whiteboard.get("acceptance_criteria", []),
    })
    support_dir = design_support_dir(session_dir, conversation_id)
    request_path = support_dir / "codex_request.json"
    if state.get("source_fingerprint") == fingerprint and request_path.is_file():
        return {"status": "reused", "request": _read_json(request_path), "request_path": str(request_path)}

    request = codex_capability_supervisor.build_escalation_request(
        goal_summary=goal,
        capability_gap=(
            "Define a coherent product and interaction design from the active Codex conversation before Provider generation. "
            "Keep each business action single-purpose with explicit input/output and a unified contract for parallel composition."
        ),
        category="planning_gap",
        librarian_context=_selected_context(whiteboard, latest_text),
        failure_evidence=[{
            "id": "prior-interface-scope-gap",
            "kind": "user_feedback",
            "summary": latest_text if state.get("reason") == "user_requested_interface_redesign" else "Interface design has not yet been reviewed.",
        }],
        prior_attempts=["A prior minimal-function interpretation could produce a CLI-only project without the expected GUI."],
        requested_outputs=("diagnosis", "provider_guidance", "acceptance_checks", "context_requests"),
    )
    _write_json(request_path, request)
    codex_capability_supervisor.append_handoff_event(agent_session, request)
    whiteboard[DESIGN_STATE_KEY] = {
        **state,
        "workflow_state": "awaiting_codex_brief",
        "source_fingerprint": fingerprint,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "request_ref": str(request_path),
    }
    session["whiteboard"] = whiteboard
    return {"status": "prepared", "request": request, "request_path": str(request_path)}


def run_codex_design_supervision(
    request_path: pathlib.Path,
    agent_session: pathlib.Path,
    *,
    codex_command: str = "",
    timeout: int = 600,
) -> dict[str, Any]:
    """Run explicitly enabled local Codex in ephemeral read-only advisory mode."""
    request_path = pathlib.Path(request_path).resolve()
    request = _read_json(request_path)
    errors = codex_capability_supervisor.validate_escalation_request(request)
    if errors:
        raise ValueError("invalid design escalation request: " + "; ".join(errors))
    executable = str(codex_command or "").strip() or shutil.which("codex") or ""
    if not executable:
        raise RuntimeError("codex executable is unavailable")
    if not DRAFT_SCHEMA.is_file():
        raise RuntimeError("Codex supervisor draft schema is unavailable")
    support_dir = request_path.parent
    draft_path = support_dir / "codex_draft.json"
    prompt = (
        "Act only as CGKN's external advisory product-design supervisor. Use only the bounded request from stdin. "
        "Design the generated product interaction, page structure, unified single-action contracts, "
        "and executable visual acceptance checks. Do not inspect or edit repository files, write candidate source, "
        "claim formal evidence, package, or deliver. Return exactly the requested JSON draft schema."
    )
    completed = subprocess.run(
        [
            executable,
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(DRAFT_SCHEMA),
            "--output-last-message",
            str(draft_path),
            prompt,
        ],
        cwd=ROOT,
        input=request_path.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, min(int(timeout), 1200)),
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Codex failed").strip()[-1600:]
        raise RuntimeError(f"Codex design supervision failed ({completed.returncode}): {detail}")
    draft = _read_json(draft_path)
    response = codex_capability_supervisor.build_supervisor_response(request, **draft)
    brief = codex_capability_supervisor.build_capability_brief(request, response)
    brief_errors = codex_capability_supervisor.validate_capability_brief(brief)
    if brief_errors:
        raise ValueError("invalid Codex design brief: " + "; ".join(brief_errors))
    response_path = _write_json(support_dir / "codex_response.json", response)
    brief_path = _write_json(support_dir / "codex_capability_brief.json", brief)
    patch = codex_capability_supervisor.whiteboard_patch_from_brief(brief)
    patch_path = _write_json(support_dir / "whiteboard_patch.json", patch)
    codex_capability_supervisor.append_handoff_event(agent_session, response)
    codex_capability_supervisor.append_handoff_event(agent_session, brief)
    return {
        "status": "ready" if brief.get("workflow_state") == "ready" else str(brief.get("workflow_state")),
        "brief": brief,
        "brief_path": str(brief_path),
        "response_path": str(response_path),
        "whiteboard_patch": patch,
        "whiteboard_patch_path": str(patch_path),
    }


def apply_design_brief(whiteboard: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Project a validated advisory brief and retain an explicit user checkpoint."""
    board = dict(whiteboard if isinstance(whiteboard, dict) else {})
    brief = result.get("brief", {}) if isinstance(result.get("brief"), dict) else {}
    errors = codex_capability_supervisor.validate_capability_brief(brief)
    if errors:
        raise ValueError("invalid design brief: " + "; ".join(errors))
    patch = result.get("whiteboard_patch", {}) if isinstance(result.get("whiteboard_patch"), dict) else {}
    supervision = patch.get("codex_capability_supervision", {}) if isinstance(patch.get("codex_capability_supervision"), dict) else {}
    board["codex_capability_supervision"] = supervision
    board["acceptance_criteria"] = _unique(
        list(board.get("acceptance_criteria", []) if isinstance(board.get("acceptance_criteria"), list) else [])
        + list(brief.get("acceptance_checks", []))
    )
    board["critical_questions"] = _unique(
        list(board.get("critical_questions", []) if isinstance(board.get("critical_questions"), list) else [])
        + list(brief.get("context_requests", [])),
        limit=40,
    )
    state = board.get(DESIGN_STATE_KEY, {}) if isinstance(board.get(DESIGN_STATE_KEY), dict) else {}
    board[DESIGN_STATE_KEY] = {
        **state,
        "workflow_state": "awaiting_user_confirmation" if brief.get("workflow_state") == "ready" else str(brief.get("workflow_state")),
        "brief_ref": str(result.get("brief_path", "")),
        "brief_sha256": brief.get("brief_sha256", ""),
        "brief_summary": str(brief.get("summary", ""))[:1200],
        "user_confirmation_required": True,
        "user_confirmed": False,
        "advisory_only": True,
    }
    board["ready_to_generate"] = False
    return board

def mark_codex_unavailable(whiteboard: dict[str, Any], error: str) -> dict[str, Any]:
    board = dict(whiteboard if isinstance(whiteboard, dict) else {})
    state = board.get(DESIGN_STATE_KEY, {}) if isinstance(board.get(DESIGN_STATE_KEY), dict) else {}
    board[DESIGN_STATE_KEY] = {
        **state,
        "workflow_state": "codex_unavailable",
        "last_error": str(error or "")[:800],
        "user_confirmed": False,
    }
    board["ready_to_generate"] = False
    return board
# End of module.
