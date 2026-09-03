#!/usr/bin/env python3
from __future__ import annotations

"""LEGACY ONLY. Not part of CGNK formal Codex conversation generation."""

import argparse
import json
import pathlib
import subprocess
import sys
import threading
from typing import Any, Callable


def build_generation_args(
    conversation_id: int | str,
    requirement: str,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    generation_mode: str = "api",
    *,
    root: pathlib.Path,
    safe_id_fn: Callable[[Any], str],
) -> argparse.Namespace:
    slug = f"codex-live-{safe_id_fn(conversation_id)}"
    result_path = pathlib.Path(log_dir) / f"{slug}_generation_result.json"
    return argparse.Namespace(
        requirement=requirement,
        project_slug=f"codex_{slug}",
        assume_defaults=False,
        allow_network=True,
        allow_provider=True,
        use_api=True,
        use_local_model=False,
        prompt_max_chars=12000,
        model=model,
        timeout=timeout,
        result_path=str(result_path),
        json=True,
        generation_mode="api",
        root=str(root),
    )


def generation_subprocess_command(args: argparse.Namespace, *, root: pathlib.Path) -> list[str]:
    legacy_entry = pathlib.Path(root) / "legacy" / "generate_project_legacy.py"
    command = [
        sys.executable,
        str(legacy_entry),
        "--requirement",
        str(args.requirement),
        "--project-slug",
        str(args.project_slug),
        "--prompt-max-chars",
        str(args.prompt_max_chars),
        "--model",
        str(args.model),
        "--timeout",
        str(args.timeout),
        "--result-path",
        str(args.result_path),
        "--json",
    ]
    command.append("--allow-network")
    command.append("--allow-provider")
    command.append("--use-api")
    if bool(getattr(args, "use_local_model", False)):
        command.append("--use-local-model")
    return command


def phase_log_path_for_project(project_slug: str, *, root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(root) / "examples" / "runtime_runs" / project_slug / "artifacts" / "generation_phase_log.jsonl"


def last_known_phase(phase_log_path: pathlib.Path) -> str:
    if not phase_log_path.exists():
        return ""
    phase = ""
    for line in phase_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("phase"):
            phase = str(doc["phase"])
    return phase


def recent_phase_events(phase_log_path: pathlib.Path, limit: int = 8) -> list[dict[str, Any]]:
    if not phase_log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in phase_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            events.append(doc)
    return events[-max(1, limit) :]


def read_timeout_diagnostics(project_slug: str, *, root: pathlib.Path) -> dict[str, Any]:
    run_dir = pathlib.Path(root) / "examples" / "runtime_runs" / project_slug
    diagnostics_path = run_dir / "agent_usage" / "usage_planning_diagnostics.json"
    if not diagnostics_path.exists():
        return {}
    try:
        doc = json.loads(diagnostics_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"path": str(diagnostics_path), "status": "unreadable", "error": str(exc)}
    if isinstance(doc, dict):
        doc.setdefault("path", str(diagnostics_path))
        return doc
    return {"path": str(diagnostics_path), "status": "invalid"}


def artifact_inventory(project_slug: str, result_path: pathlib.Path, phase_log_path: pathlib.Path, *, root: pathlib.Path) -> tuple[list[str], list[str]]:
    run_dir = pathlib.Path(root) / "examples" / "runtime_runs" / project_slug
    project_dir = pathlib.Path(root) / "generated" / project_slug
    paths = {
        "generation_result.json": result_path,
        "generation_phase_log.jsonl": phase_log_path,
        "product_studio_run.json": run_dir / "artifacts" / "product_studio_run.json",
        "usage_plan.json": run_dir / "agent_usage" / "usage_plan.json",
        "runtime_check.json": run_dir / "agent_usage" / "runtime_check.json",
        "visual_evidence_plan.json": run_dir / "agent_usage" / "visual_evidence_plan.json",
        "usage_planning_diagnostics.json": run_dir / "agent_usage" / "usage_planning_diagnostics.json",
        "README.md": project_dir / "README.md",
    }
    detected: list[str] = []
    missing: list[str] = []
    for name, path in paths.items():
        (detected if path.exists() else missing).append(name)
    return detected, missing


def write_timeout_failure_result(
    args: argparse.Namespace,
    timeout_seconds: int,
    result_path: pathlib.Path,
    *,
    root: pathlib.Path,
    now_fn: Callable[[], str],
    write_json_fn: Callable[[pathlib.Path, dict[str, Any]], None],
) -> dict[str, Any]:
    phase_log_path = phase_log_path_for_project(str(args.project_slug), root=root)
    detected, missing = artifact_inventory(str(args.project_slug), result_path, phase_log_path, root=root)
    result = {
        "kind": "CustomerProjectGenerationResult",
        "created_at": now_fn(),
        "status": "BLOCKED",
        "reason": "generation subprocess exceeded total timeout",
        "timeout_seconds": timeout_seconds,
        "last_known_phase": last_known_phase(phase_log_path),
        "recent_phase_events": recent_phase_events(phase_log_path),
        "timeout_diagnostics": read_timeout_diagnostics(str(args.project_slug), root=root),
        "artifacts_detected": detected,
        "missing_artifacts": missing,
        "phase_log_path": str(phase_log_path),
        "can_retry": True,
        "retry_should_reuse": [
            "product_studio_run.json",
            "customer_intent.raw_user_message",
            "output_contract",
            "frozen_project_type",
        ],
    }
    write_json_fn(result_path, result)
    write_json_fn(result_path.with_name(result_path.stem.replace("_generation_result", "_failure_result") + ".json"), result)
    return result


def run_generation_subprocess(
    args: argparse.Namespace,
    log_dir: pathlib.Path,
    *,
    root: pathlib.Path,
    append_jsonl_fn: Callable[[pathlib.Path, dict[str, Any]], None],
    now_fn: Callable[[], str],
    write_json_fn: Callable[[pathlib.Path, dict[str, Any]], None],
    total_timeout_seconds: int,
) -> dict[str, Any]:
    command = generation_subprocess_command(args, root=root)
    result_path = pathlib.Path(str(args.result_path))
    timeout_seconds = max(total_timeout_seconds, int(args.timeout) + 180)
    try:
        proc = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        failure_result = write_timeout_failure_result(args, timeout_seconds, result_path, root=root, now_fn=now_fn, write_json_fn=write_json_fn)
        append_jsonl_fn(
            pathlib.Path(log_dir) / "generation_subprocess.jsonl",
            {
                "created_at": now_fn(),
                "event": "generation_subprocess_timeout",
                "project_slug": str(args.project_slug),
                "timeout_seconds": timeout_seconds,
                "failure_result_path": str(result_path),
                "stdout_tail": str(exc.stdout or "")[-2000:],
                "stderr_tail": str(exc.stderr or "")[-2000:],
            },
        )
        return failure_result
    append_jsonl_fn(
        pathlib.Path(log_dir) / "generation_subprocess.jsonl",
        {
            "created_at": now_fn(),
            "event": "generation_subprocess_finished",
            "project_slug": str(args.project_slug),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        },
    )
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8", errors="replace"))
    if proc.returncode != 0:
        raise RuntimeError(f"generation subprocess failed before writing result: {proc.stderr[-1200:] or proc.stdout[-1200:]}")
    raise RuntimeError("generation subprocess completed without writing result")


def safe_generation_failure_facts(requirement: str, exc: Exception) -> dict[str, Any]:
    error = str(exc)
    category = "generation_pipeline_error"
    user_visible_cause = "后台生成流程中断，项目文件、测试和预览还没有完成。"
    if "prompt_max_chars" in error or "Namespace" in error:
        category = "generation_bridge_configuration_error"
        user_visible_cause = "后台生成入口配置缺少必需参数，流程在进入项目文件生成前中断。"
    elif "context prompt quality failed" in error.lower() or "prompt exceeds max_chars" in error.lower():
        category = "context_prompt_budget_error"
        user_visible_cause = "长期项目记忆和本轮需求压缩后仍超过当前生成上下文预算，流程在进入项目文件生成前中断。"
    elif "timeout" in error.lower():
        category = "generation_timeout"
        user_visible_cause = "后台生成超过本轮总等待时间，项目文件、测试或预览还没有完整返回。"
    elif "api" in error.lower() or "provider" in error.lower():
        category = "provider_generation_error"
        user_visible_cause = "后台生成模型/API 调用中断，项目文件、测试和预览还没有完整返回。"
    return {
        "requirement": requirement,
        "error_category": category,
        "user_visible_cause": user_visible_cause,
        "impact": "No project delivery, tests, screenshots, images, or videos were completed in this run.",
        "next_step": "Keep the captured project memory, fix the backend issue, and retry generation.",
        "technical_error_logged": True,
        "policy": "provider-only; no local template fallback",
    }


def generation_progress_text(elapsed_seconds: int) -> str:
    minutes = max(1, int(round(elapsed_seconds / 60)))
    return (
        f"后台仍在生成中，已运行约 {minutes} 分钟。"
        "我目前只能确认生成流程还没有写出最终交付结果；不会把尚未验证的阶段说成已完成。"
        "完成后我会再发送项目结果、测试状态，以及实际存在的截图/图片/视频预览。"
    )


def run_generation_job(
    bridge: Any,
    client: Any,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    announce_start: bool = False,
    control_id: str = "",
    generation_mode: str = "api",
) -> None:
    session = bridge.load_session(session_dir, conversation_id)
    if session.get("generation", {}).get("status") == "running":
        return
    requirement = bridge.combined_requirement(session)
    if not requirement:
        if not bridge.send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="missing_requirement_before_generation",
            session=session,
            facts={"reason": "user asked to generate before a usable project requirement was captured"},
            model=model,
            timeout=timeout,
        ):
            bridge.send_customer_reply(
                client,
                conversation_id,
                session_dir,
                session,
                event="missing_requirement_before_generation",
                facts={"message": "当前没有可执行项目目标；后台未启动。"},
            )
        return
    if control_id:
        bridge.update_backend_control_status(session, control_id, "running")
    session["generation"] = {
        "status": "running",
        "driver": "legacy_provider_pipeline",
        "started_at": bridge.now(),
        "control_id": control_id,
        "generation_mode": str(generation_mode or "api"),
    }
    bridge.append_memory_event(session, "generation_started", data={"requirement": requirement[:6000], "generation_mode": str(generation_mode or "api"), "control_id": control_id})
    bridge.save_session(session_dir, session)
    if announce_start:
        bridge.send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="generation_started",
            session=session,
            facts={
                "requirement": requirement,
                "policy": "legacy provider project generation; no local template fallback",
                "important": "Generation has just started. Do not claim tests passed or project completed.",
            },
            model=model,
            timeout=timeout,
        )
        bridge.save_session(session_dir, session)
    stop_progress = threading.Event()

    def progress_worker() -> None:
        for step in range(2):
            elapsed = 120 * (step + 1)
            if stop_progress.wait(120):
                return
            current = bridge.load_session(session_dir, conversation_id)
            if current.get("generation", {}).get("status") != "running":
                return
            bridge.send_customer_reply(
                client,
                conversation_id,
                session_dir,
                current,
                event="generation_progress",
                facts={"elapsed_seconds": elapsed},
                source="generation_progress",
                direct_text=generation_progress_text(elapsed),
            )

    threading.Thread(target=progress_worker, daemon=True).start()
    args = bridge.build_generation_args(conversation_id, requirement, log_dir, model, timeout, generation_mode)
    try:
        bridge.assert_api_generation_ready(generation_mode)
        result = bridge.run_generation_subprocess(args, log_dir)
    except Exception as exc:
        stop_progress.set()
        session = bridge.load_session(session_dir, conversation_id)
        if control_id:
            bridge.update_backend_control_status(session, control_id, "failed", reason=str(exc))
        session["generation"] = {
            "status": "failed",
            "driver": "legacy_provider_pipeline",
            "finished_at": bridge.now(),
            "error": str(exc),
            "control_id": control_id,
            "generation_mode": str(generation_mode or "api"),
        }
        safe_facts = safe_generation_failure_facts(requirement, exc)
        bridge.append_memory_event(session, "generation_failed", data={"error": str(exc), "safe_facts": safe_facts})
        bridge.save_session(session_dir, session)
        bridge.log_bridge_error(log_dir, "generation_failed", conversation_id, exc, {"requirement": requirement})
        bridge.send_provider_or_technical_error(
            client,
            conversation_id,
            session_dir,
            event="generation_failed",
            session=session,
            facts=safe_facts,
            model=model,
            timeout=timeout,
            technical_error=str(exc),
        )
        bridge.save_session(session_dir, session)
        return
    stop_progress.set()
    session = bridge.load_session(session_dir, conversation_id)
    status = str(result.get("status", "unknown")).upper()
    session["generation"] = {
        "status": result.get("status", "unknown"),
        "driver": "legacy_provider_pipeline",
        "finished_at": bridge.now(),
        "result_path": str(args.result_path),
        "control_id": control_id,
        "generation_mode": str(generation_mode or "api"),
    }
    if control_id:
        bridge.update_backend_control_status(session, control_id, "completed" if status == "PASS" else "completed", result_path=str(args.result_path))
    bridge.append_memory_event(session, "generation_finished", data={"status": result.get("status", "unknown"), "result_path": str(args.result_path)})
    bridge.save_session(session_dir, session)
    if status == "PASS":
        image_candidates = bridge.delivery_image_candidates(result)
        image = image_candidates[0] if image_candidates else None
        try:
            bridge.emit_delivery_evidence(session_dir, session, result, image, log_dir)
            evidence = bridge.delivery_evidence_state(bridge.read_truth_ledger(session_dir, conversation_id))
            bridge.send_delivery_artifacts(client, conversation_id, session_dir, session, evidence)
        except Exception as exc:
            bridge.log_bridge_error(log_dir, "emit_delivery_evidence_failed", conversation_id, exc, {"result_path": str(args.result_path)})
        bridge.send_provider_message(client, conversation_id, session_dir, event="generation_passed", session=session, facts=bridge.project_delivery_facts(result), model=model, timeout=timeout)
        bridge.save_session(session_dir, session)
    else:
        bridge.send_provider_message(
            client,
            conversation_id,
            session_dir,
            event="generation_completed_non_pass",
            session=session,
            facts={"status": status, "project_dir": result.get("project_dir"), "execution_path": result.get("execution_path")},
            model=model,
            timeout=timeout,
        )
        bridge.save_session(session_dir, session)
