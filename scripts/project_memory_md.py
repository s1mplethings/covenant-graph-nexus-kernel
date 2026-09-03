#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_DIR = ROOT / "examples" / "project_memory"
FLOW_REF = "flow.modular_project_generation@1"
POLICY_REF = "policy.safe_modular_project_generation@1"
CONTRACT_PACK_REF = "agent_context.modular_project_generation.contract_pack.json"

MODULE_ROWS = [
    ("n_customer_service", "module.customer.service@1", "customer_request", "需求对话、用户纠正、验收标准、交付要求"),
    ("n_requirement_blueprint", "module.requirement_blueprint.generator@1", "requirement_blueprint", "需求蓝图、I/O、功能拆解、任务和 PRD"),
    ("n_local_librarian", "module.local.librarian@1", "local_library_index", "本地库、模块、脚本和可复用能力索引"),
    ("n_online_library_sources", "module.online.library_sources@1", "online_sources", "市场调研、在线库/API/模型发现"),
    ("n_feature_library_search", "module.feature.library_search@1", "candidates", "按功能寻找可用库、API、skill 或 agent"),
    ("n_local_agent", "module.local_agent.plan@1", "agent_plan", "agent 真实使用项目的输入到输出流程计划"),
    ("n_adversarial_generation", "module.adversarial_generation@1", "adversarial_review", "反向检查模板化、假通过、缺产物、未满足用户纠正"),
    ("n_project_generator", "module.project.generator@1", "project_blueprint/generation_trace", "真实项目代码、接口、依赖和生成轨迹"),
    ("n_test_graph_emit", "module.test_graph.emit@1", "test_graph", "项目类型自适应测试图和步骤"),
    ("n_effect_report_emit", "module.effect_report.emit@1", "effect_report", "效果报告、截图、视频、可见产物"),
    ("n_unified_control", "module.unified_control@1", "project_blueprint/generation_trace/test_graph/effect_report", "最终统一验收与交付裁决"),
]

ARTIFACT_ROWS = [
    ("artifact.goal@1", "用户原始目标和补充"),
    ("artifact.customer_request@1", "规范化客户请求、约束、验收和纠正"),
    ("artifact.requirement_blueprint@1", "结构化需求蓝图"),
    ("artifact.local_library_index@1", "本地能力索引"),
    ("artifact.online_library_sources@1", "在线资料、市场调研和 API/模型发现"),
    ("artifact.feature_library_candidates@1", "按功能筛出的候选库/API/skill"),
    ("artifact.local_agent_plan@1", "agent 实际使用计划"),
    ("artifact.adversarial_review@1", "生成前/后的反向验收意见"),
    ("artifact.project_blueprint@1", "项目文件、模块、接口和运行方式"),
    ("artifact.generation_trace@1", "生成过程、决策和模块输出"),
    ("artifact.test_graph@1", "测试图"),
    ("artifact.effect_report@1", "效果报告和可见产物"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_id(value: Any) -> str:
    text = str(value or "session").strip()
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in text)[:120] or "session"


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def user_messages(session: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for msg in session.get("messages", []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            text = str(msg.get("text", "")).strip()
            if text and not text.startswith("/"):
                out.append(text)
    return out


def uploaded_inputs(session: dict[str, Any]) -> list[dict[str, Any]]:
    values = session.get("attachments", [])
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values[-120:]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "type": str(item.get("type", "")).strip(),
                "file_name": str(item.get("file_name", "")).strip(),
                "mime_type": str(item.get("mime_type", "")).strip(),
                "file_size": item.get("file_size", 0),
                "caption": str(item.get("caption", "")).strip(),
                "local_path": str(item.get("local_path", "")).strip(),
                "created_at": str(item.get("created_at", "")).strip(),
            }
        )
    return out


def uploaded_input_lines(session: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in uploaded_inputs(session):
        name = item.get("file_name", "") or "未命名上传"
        kind = item.get("type", "") or "file"
        path = item.get("local_path", "")
        mime = item.get("mime_type", "")
        caption = item.get("caption", "")
        line = f"{kind}: {name}"
        if mime:
            line += f"; mime_type: {mime}"
        if path:
            line += f"; local_path: {path}"
        if caption:
            line += f"; caption: {caption}"
        lines.append(line)
    return lines


def section_list(title: str, items: list[str]) -> str:
    body = "\n".join(f"- {item}" for item in items) if items else "- 未记录"
    return f"## {title}\n\n{body}\n"


def table(rows: list[tuple[str, str, str, str]]) -> str:
    lines = ["| Flow Node | Module Ref | Main Output | Responsibility |", "| --- | --- | --- | --- |"]
    lines.extend(f"| `{a}` | `{b}` | `{c}` | {d} |" for a, b, c, d in rows)
    return "\n".join(lines)


def artifact_table() -> str:
    lines = ["| Artifact Ref | Purpose |", "| --- | --- |"]
    lines.extend(f"| `{a}` | {b} |" for a, b in ARTIFACT_ROWS)
    return "\n".join(lines)


def build_project_memory_artifact(session: dict[str, Any], md_path: pathlib.Path) -> dict[str, Any]:
    whiteboard = session.get("whiteboard", {})
    if not isinstance(whiteboard, dict):
        whiteboard = {}
    return {
        "kind": "ProjectMemoryMarkdown",
        "artifact_ref": "artifact.project_memory_markdown@1",
        "schema_version": "1",
        "generated_at": utc_now(),
        "conversation_id": str(session.get("conversation_id", "")),
        "markdown_path": str(md_path),
        "flow_ref": FLOW_REF,
        "policy_ref": POLICY_REF,
        "contract_pack": CONTRACT_PACK_REF,
        "customer_request": {
            "project_summary": str(whiteboard.get("project_summary", "")).strip(),
            "known_facts": string_list(whiteboard.get("known_facts")),
            "default_assumptions": string_list(whiteboard.get("default_assumptions")),
            "user_rules": string_list(whiteboard.get("user_rules")),
            "acceptance_criteria": string_list(whiteboard.get("acceptance_criteria")),
            "change_requests": string_list(whiteboard.get("change_requests")),
            "delivery_requirements": string_list(whiteboard.get("delivery_requirements")),
            "decision_log": string_list(whiteboard.get("decision_log")),
            "open_questions": string_list(whiteboard.get("open_questions")),
            "blocking_questions": string_list(whiteboard.get("blocking_questions")),
        },
        "uploaded_inputs": uploaded_inputs(session),
        "visible_user_messages": user_messages(session),
        "generation": session.get("generation", {}),
        "module_mapping": [
            {"node": a, "module_ref": b, "main_output": c, "responsibility": d}
            for a, b, c, d in MODULE_ROWS
        ],
        "artifact_mapping": [{"artifact_ref": a, "purpose": b} for a, b in ARTIFACT_ROWS],
        "revision_count": len(session.get("whiteboard_versions", []) if isinstance(session.get("whiteboard_versions"), list) else []),
    }


def build_project_memory_md(session: dict[str, Any], artifact_path: pathlib.Path) -> str:
    whiteboard = session.get("whiteboard", {})
    if not isinstance(whiteboard, dict):
        whiteboard = {}
    generation = session.get("generation", {})
    if not isinstance(generation, dict):
        generation = {}
    revision_count = len(session.get("whiteboard_versions", []) if isinstance(session.get("whiteboard_versions"), list) else [])
    parts = [
        "---",
        "kind: ProjectMemoryMarkdown",
        "schema_version: 1",
        f"conversation_id: {session.get('conversation_id', '')}",
        f"flow_ref: {FLOW_REF}",
        f"policy_ref: {POLICY_REF}",
        f"contract_pack: {CONTRACT_PACK_REF}",
        "artifact_ref: artifact.project_memory_markdown@1",
        f"generated_at: {utc_now()}",
        f"revision_count: {revision_count}",
        "---",
        "",
        "# Project Memory",
        "",
        "这份文档是 Codex conversation 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。",
        "",
        "## Modular Contract Binding",
        "",
        f"- Contract pack: `{CONTRACT_PACK_REF}`",
        f"- Flow: `{FLOW_REF}`",
        f"- Policy: `{POLICY_REF}`",
        f"- JSON artifact mirror: `{artifact_path}`",
        "",
        "## Current Project Summary",
        "",
        str(whiteboard.get("project_summary", "")).strip() or "未记录",
        "",
        section_list("Known Facts", string_list(whiteboard.get("known_facts"))),
        section_list("User Rules", string_list(whiteboard.get("user_rules"))),
        section_list("Default Assumptions", string_list(whiteboard.get("default_assumptions"))),
        section_list("First Version Plan", string_list(whiteboard.get("first_version_plan"))),
        section_list("Acceptance Criteria", string_list(whiteboard.get("acceptance_criteria"))),
        section_list("Change Requests", string_list(whiteboard.get("change_requests"))),
        section_list("Delivery Requirements", string_list(whiteboard.get("delivery_requirements"))),
        section_list("Decision Log", string_list(whiteboard.get("decision_log"))),
        section_list("Uploaded Project Inputs", uploaded_input_lines(session)),
        section_list("Open Questions", string_list(whiteboard.get("open_questions"))),
        section_list("Blocking Questions", string_list(whiteboard.get("blocking_questions"))),
        "## Module Map",
        "",
        table(MODULE_ROWS),
        "",
        "## Artifact Map",
        "",
        artifact_table(),
        "",
        "## Visible User Message Log",
        "",
    ]
    messages = user_messages(session)
    parts.extend(f"{idx}. {text}" for idx, text in enumerate(messages, 1)) if messages else parts.append("- 未记录")
    parts.extend([
        "",
        "## Generation State",
        "",
        f"- Status: `{generation.get('status', 'idle')}`",
        f"- Started at: `{generation.get('started_at', '')}`",
        f"- Finished at: `{generation.get('finished_at', '')}`",
        f"- Result path: `{generation.get('result_path', '')}`",
        "",
        "## Update Rules",
        "",
        "- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。",
        "- 长期行为要求写入 `User Rules`。",
        "- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。",
        "- 模型/API/库选择原因写入 `Decision Log`。",
        "- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。",
        "",
    ])
    return "\n".join(parts)


def write_project_memory(session: dict[str, Any], memory_dir: pathlib.Path | None = None) -> dict[str, str]:
    base = memory_dir or DEFAULT_MEMORY_DIR
    target = base / safe_id(session.get("conversation_id", "session"))
    target.mkdir(parents=True, exist_ok=True)
    md_path = target / "PROJECT_MEMORY.md"
    artifact_path = target / "project_memory.artifact.json"
    md_path.write_text(build_project_memory_md(session, artifact_path), encoding="utf-8")
    artifact_path.write_text(json.dumps(build_project_memory_artifact(session, md_path), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"project_memory_md": str(md_path), "project_memory_artifact": str(artifact_path)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("session_json")
    args = parser.parse_args()
    session = json.loads(pathlib.Path(args.session_json).read_text(encoding="utf-8"))
    print(json.dumps(write_project_memory(session), ensure_ascii=False, indent=2))
