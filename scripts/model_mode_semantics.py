from __future__ import annotations

import re
from typing import Any


def _compact(text: str) -> str:
    return re.sub(r"[\s,.!?。！？~～+＋、，：:；;\"'“”‘’（）()]+", "", str(text or "").lower())


def _target_project_local_requested(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "走本地模型",
            "用本地模型",
            "本地模型开始",
            "项目里面用本地模型",
            "项目里用本地模型",
            "后端接本地模型",
            "接本地模型",
            "不要用外部接口做推理",
            "不要外部接口做推理",
            "不用外部接口做推理",
            "本地推理",
            "localmodel",
        )
    )


def _target_project_api_requested(compact: str) -> bool:
    return any(token in compact for token in ("项目里面用api", "项目里用api", "项目接api模型", "api模型推理", "外部模型推理"))


def _platform_no_api_requested(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "你们生成代码不要走api",
            "生成代码不要走api",
            "生成过程不要走接口",
            "生成过程不要用api",
            "你这个系统生成代码也必须走本地模型",
            "cgkn自己也必须用本地模型生成",
            "cgnk自己也必须用本地模型生成",
            "你们自己也必须走本地模型",
            "你们也不要用api生成",
            "平台生成不要用api",
        )
    )


def _platform_api_allowed(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "继续生成",
            "继续推进",
            "用当前可用生成方式",
            "先用当前可用生成方式",
            "切到当前可用生成方式",
            "允许当前可用生成方式",
        )
    )


def parse_model_mode_semantics(user_text: str, session: dict[str, Any] | None = None) -> dict[str, Any]:
    compact = _compact(user_text)
    target_mode = "unspecified"
    target_source = "default"
    target_notes: list[str] = []
    config_needed = False

    if _target_project_local_requested(compact):
        target_mode = "local_model"
        target_source = "user_requested"
        config_needed = True
        target_notes.extend(
            [
                "生成出来的项目应按本地模型推理路线设计。",
                "需要模型路径或本地推理服务 endpoint 配置入口。",
                "缺少本地模型文件或服务时不能宣称真实推理通过。",
            ]
        )
    elif _target_project_api_requested(compact):
        target_mode = "api_model"
        target_source = "user_requested"
        config_needed = True
        target_notes.append("生成出来的项目应包含外部模型配置入口和缺配置限制说明。")

    backend_mode = "none"
    backend_source = "default"
    backend_notes: list[str] = []
    no_api = False

    if _platform_no_api_requested(compact):
        backend_mode = "local"
        backend_source = "user_explicit_platform_constraint"
        no_api = True
        backend_notes.append("用户明确限制 CGKN 生成过程不能使用 API。")
    elif _platform_api_allowed(compact):
        backend_mode = "api"
        backend_source = "user_explicit_platform_constraint"
        backend_notes.append("用户明确允许 CGKN 生成过程使用当前可用生成方式。")

    if target_mode != "unspecified" and backend_mode == "none":
        reason = "用户描述的是生成项目内部模型方案，不是 CGKN 平台生成后端限制。"
        confidence = 0.92
    elif backend_mode != "none":
        reason = "用户明确提到了 CGKN/生成过程/可用生成方式等平台执行约束。"
        confidence = 0.88
    else:
        reason = "未发现明确模型模式或平台生成后端约束。"
        confidence = 0.35

    return {
        "target_project_model": {
            "mode": target_mode,
            "source": target_source,
            "config_needed": config_needed,
            "notes": target_notes,
            "config_keys": ["MODEL_PATH", "LOCAL_MODEL_ENDPOINT"] if target_mode == "local_model" else [],
            "acceptance_limits": ["缺少模型文件或本地推理服务时不能宣称真实推理通过"] if target_mode == "local_model" else [],
        },
        "cgkn_generation_backend_constraint": {
            "mode": backend_mode,
            "source": backend_source,
            "no_api": no_api,
            "notes": backend_notes,
        },
        "confidence": confidence,
        "reason": reason,
    }


def apply_model_mode_semantics(
    session: dict[str, Any],
    user_text: str,
    *,
    configured_backend_mode: str = "api",
    configured_model: str = "",
) -> dict[str, Any]:
    semantics = parse_model_mode_semantics(user_text, session)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}

    target = semantics["target_project_model"]
    if target.get("mode") != "unspecified":
        architecture = whiteboard.get("target_project_architecture", {}) if isinstance(whiteboard.get("target_project_architecture"), dict) else {}
        architecture.update(
            {
                "model_mode": target.get("mode"),
                "model_config_needed": bool(target.get("config_needed")),
                "model_adapter_required": target.get("mode") in {"local_model", "api_model", "hybrid"},
                "model_config_keys": list(target.get("config_keys", [])),
                "acceptance_limits": list(target.get("acceptance_limits", [])),
                "notes": list(target.get("notes", [])),
                "source": target.get("source", "user_requested"),
            }
        )
        whiteboard["target_project_architecture"] = architecture
        known_facts = whiteboard.get("known_facts", []) if isinstance(whiteboard.get("known_facts"), list) else []
        if target.get("mode") == "local_model":
            known_facts.append("生成出来的项目内部按本地模型路线设计，需要模型适配层、配置入口和缺模型限制说明。")
        whiteboard["known_facts"] = _unique_strings([str(item) for item in known_facts if str(item).strip()])

    backend = semantics["cgkn_generation_backend_constraint"]
    execution = whiteboard.get("cgkn_execution", {}) if isinstance(whiteboard.get("cgkn_execution"), dict) else {}
    execution.update(
        {
            "generation_backend": str(configured_backend_mode or "api"),
            "model": str(configured_model or ""),
            "platform_generation_constraint": backend.get("mode") if backend.get("mode") in {"api", "local"} else "none",
            "platform_no_api": bool(backend.get("no_api")),
        }
    )
    whiteboard["cgkn_execution"] = execution
    session["whiteboard"] = whiteboard
    session["model_mode_semantics"] = semantics
    return semantics


def _unique_strings(values: list[str], limit: int = 80) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out
