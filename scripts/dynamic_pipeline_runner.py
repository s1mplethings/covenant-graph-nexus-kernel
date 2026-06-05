#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Any, Callable

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import agent_conversation_loop
import check_connectivity
import local_agent_actions
import pipeline_manifest
import pipeline_planner_agent


AgentCallable = Callable[[list[dict[str, Any]], str, int], str | dict[str, Any]]


def _role_by_id(manifest: dict[str, Any], role_id: str) -> dict[str, Any]:
    for role in manifest.get("roles", []):
        if isinstance(role, dict) and str(role.get("id", "")) == role_id:
            return role
    return {"id": role_id, "name": role_id or "Pipeline Agent", "purpose": "Execute this pipeline step."}


def _system_prompt(role: dict[str, Any], step: dict[str, Any], manifest: dict[str, Any]) -> str:
    allowed = step.get("allowed_actions", [])
    return f"""You are {role.get('name')}.
Role purpose: {role.get('purpose')}.
Current step goal: {step.get('goal')}.
You must read the latest whiteboard, generation_context_snapshot, pipeline_manifest, and tool_result events in the provided session history.
You may only use these action types: {json.dumps(allowed, ensure_ascii=False)}.
Return JSON only:
{{
  "message": "short status",
  "actions": [
    {{"type": "write_file", "path": "README.md", "content": "..."}}
  ]
}}
Do not claim delivery is complete. Do not call old CGNK paths like generate_project.py, run_local_pipeline, or simulator.
Pipeline manifest:
{json.dumps(manifest, ensure_ascii=False)[:12000]}"""


def collect_generation_context(session_path: str | pathlib.Path, whiteboard: dict[str, Any] | None = None) -> str:
    return pipeline_planner_agent.collect_generation_context(session_path, whiteboard or {})


def _history_for_step(session_path: pathlib.Path, system_prompt: str) -> list[dict[str, Any]]:
    events = agent_conversation_loop.read_session(session_path)
    return [{"kind": "step_system_prompt", "role": "system", "content": system_prompt}] + events


def _call_step_provider(events: list[dict[str, Any]], model: str, timeout: int) -> str:
    if str(model).startswith("gpt-test"):
        raise RuntimeError("test model does not call provider")
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for dynamic pipeline runner")
    root = str(creds.get("base_url", "")).rstrip("/")
    system = str(events[0].get("content", "")) if events else ""
    history = "\n".join(f"{event.get('kind', 'event')}: {json.dumps(event, ensure_ascii=False)}" for event in events[1:])[-60000:]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": history}]
    if check_connectivity._is_gptsapi_base_url(root):
        endpoint = root + "/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 1800}
    else:
        endpoint = root + "/responses"
        payload = {
            "model": model,
            "input": "\n".join(f"{item['role']}: {item['content']}" for item in messages),
            "temperature": 0.2,
            "max_output_tokens": 1800,
        }
    last_error = ""
    for attempt in range(3):
        doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
        if doc is not None:
            text = check_connectivity._extract_text(doc)
            if text:
                return text
        last_error = error
        time.sleep(min(5.0, 1.2 * (attempt + 1)))
    raise RuntimeError(last_error or "empty dynamic pipeline agent response")


def _forbidden_command(command: str) -> bool:
    lowered = str(command or "").lower()
    return any(pattern in lowered for pattern in pipeline_manifest.FORBIDDEN_LEGACY_PATTERNS)


def _execute_manifest_action(
    executor: local_agent_actions.LocalAgentActionExecutor,
    action: dict[str, Any],
    allowed_actions: set[str],
) -> dict[str, Any]:
    action_type = str(action.get("type") or action.get("action") or "").strip()
    if action_type not in allowed_actions:
        return {"ok": False, "type": action_type, "error": f"action type not allowed for this step: {action_type}"}
    if action_type == "run_command" and _forbidden_command(str(action.get("command", ""))):
        return {"ok": False, "type": action_type, "error": "legacy generation command rejected"}
    return executor.execute(action)


def _nested_action(step: dict[str, Any]) -> dict[str, Any]:
    return step.get("action", {}) if isinstance(step.get("action"), dict) else {}


def _step_action(step: dict[str, Any]) -> dict[str, Any]:
    step_type = str(step.get("type", ""))
    nested = _nested_action(step)
    if step_type == "package_project":
        return {"type": "package_project", "startup_command": str(step.get("startup_command", "")), "known_limits": step.get("known_limits", [])}
    if step_type == "run_command":
        return {"type": "run_command", "command": str(step.get("command") or nested.get("command", ""))}
    if step_type == "use_skill":
        return {
            "type": "use_skill",
            "name": str(step.get("name") or step.get("skill") or nested.get("name", "")),
            "args": step.get("args") if isinstance(step.get("args"), dict) else nested.get("args", {}),
        }
    return {}


def _run_agent_turn(
    *,
    session_file: pathlib.Path,
    executor: local_agent_actions.LocalAgentActionExecutor,
    manifest: dict[str, Any],
    step: dict[str, Any],
    model: str,
    timeout: int,
    max_turns: int,
    agent: AgentCallable | None,
) -> dict[str, Any]:
    role = _role_by_id(manifest, str(step.get("role", "")))
    allowed_actions = {str(item) for item in step.get("allowed_actions", [])}
    agent_fn = agent or _call_step_provider
    last_error = ""
    for turn in range(1, max(1, max_turns) + 1):
        system_prompt = _system_prompt(role, step, manifest)
        events = _history_for_step(session_file, system_prompt)
        try:
            response = agent_fn(events, model, timeout)
        except Exception as exc:
            last_error = str(exc)
            agent_conversation_loop.append_event(
                session_file,
                {"kind": "agent_error", "role": role.get("id"), "step_id": step.get("id"), "turn": turn, "error": last_error},
            )
            continue
        parsed = agent_conversation_loop.parse_agent_response(response)
        actions = parsed.get("actions", [])
        agent_conversation_loop.append_event(
            session_file,
            {
                "kind": "assistant",
                "role": role.get("id"),
                "step_id": step.get("id"),
                "turn": turn,
                "message": parsed.get("message", ""),
                "actions": actions,
            },
        )
        if not actions:
            last_error = "agent returned no actions"
            agent_conversation_loop.append_event(
                session_file,
                {"kind": "tool_result", "role": role.get("id"), "step_id": step.get("id"), "turn": turn, "ok": False, "error": last_error},
            )
            continue
        failed = False
        package_result: dict[str, Any] | None = None
        for action in actions:
            agent_conversation_loop.append_event(session_file, {"kind": "action", "role": role.get("id"), "step_id": step.get("id"), "turn": turn, "action": action})
            result = _execute_manifest_action(executor, action, allowed_actions)
            agent_conversation_loop.append_event(
                session_file,
                {"kind": "tool_result", "role": role.get("id"), "step_id": step.get("id"), "turn": turn, "action": action, "result": result},
            )
            if not result.get("ok"):
                failed = True
                last_error = str(result.get("error") or "action failed")
            if str(action.get("type") or action.get("action") or "") == "package_project" and result.get("ok"):
                package_result = result
        if package_result:
            return {"status": "ok", "summary": "package_project action completed", "package_result": package_result}
        if not failed:
            return {"status": "ok", "summary": str(parsed.get("message") or "step completed")}
    return {"status": "failed", "summary": last_error or "agent step failed"}


def _fallback_to_agent_loop(
    *,
    session_file: pathlib.Path,
    project: pathlib.Path,
    model: str,
    timeout: int,
    max_turns: int,
    reason: str,
) -> dict[str, Any]:
    agent_conversation_loop.append_event(session_file, {"kind": "pipeline_fallback", "role": "system", "reason": reason})
    result = agent_conversation_loop.run_agent_loop(
        session_path=session_file,
        project_dir=project,
        model=model,
        timeout=timeout,
        max_turns=max_turns,
    )
    result["driver"] = "agent_conversation_loop_fallback"
    return result


def run_dynamic_pipeline(
    *,
    session_path: str | pathlib.Path,
    project_dir: str | pathlib.Path,
    pipeline_manifest: dict[str, Any],
    model: str = "gpt-4.1",
    timeout: int = 120,
    max_turns: int = 12,
    agent: AgentCallable | None = None,
    fallback_to_agent_loop: bool = True,
) -> dict[str, Any]:
    session_file = pathlib.Path(session_path).resolve()
    project = pathlib.Path(project_dir).resolve()
    ok, errors = pipeline_manifest_module.validate_pipeline_manifest(pipeline_manifest)
    if not ok:
        reason = "; ".join(errors)
        if fallback_to_agent_loop:
            return _fallback_to_agent_loop(session_file=session_file, project=project, model=model, timeout=timeout, max_turns=max_turns, reason=reason)
        raise RuntimeError(reason)

    executor = local_agent_actions.LocalAgentActionExecutor(project)
    agent_conversation_loop.append_event(session_file, {"kind": "pipeline_manifest", "role": "system", "manifest": pipeline_manifest})
    limits = pipeline_manifest.get("limits", {}) if isinstance(pipeline_manifest.get("limits"), dict) else {}
    per_step_turns = max(1, min(int(limits.get("max_agent_turns_per_step", 3) or 3), max(1, int(max_turns or 1))))
    max_steps = max(1, min(int(limits.get("max_total_steps", 12) or 12), 12))
    package_result: dict[str, Any] | None = None

    try:
        for step in pipeline_manifest.get("steps", [])[:max_steps]:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id", ""))
            step_type = str(step.get("type", ""))
            if step_type == "agent_turn":
                result = _run_agent_turn(
                    session_file=session_file,
                    executor=executor,
                    manifest=pipeline_manifest,
                    step=step,
                    model=model,
                    timeout=timeout,
                    max_turns=per_step_turns,
                    agent=agent,
                )
                agent_conversation_loop.append_event(
                    session_file,
                    {
                        "kind": "pipeline_step_result",
                        "step_id": step_id,
                        "role": step.get("role"),
                        "status": result.get("status"),
                        "summary": result.get("summary", ""),
                    },
                )
                if result.get("package_result"):
                    package_result = result["package_result"]
                    break
                if result.get("status") != "ok":
                    raise RuntimeError(f"pipeline step failed: {step_id}: {result.get('summary', '')}")
            elif step_type in {"use_skill", "run_command", "package_project"}:
                action = _step_action(step)
                allowed = {action["type"]} if action.get("type") else set()
                if action.get("type") == "run_command" and _forbidden_command(str(action.get("command", ""))):
                    result = {"ok": False, "type": "run_command", "error": "legacy generation command rejected"}
                else:
                    result = _execute_manifest_action(executor, action, allowed)
                agent_conversation_loop.append_event(session_file, {"kind": "action", "role": "system", "step_id": step_id, "action": action})
                agent_conversation_loop.append_event(session_file, {"kind": "tool_result", "role": "system", "step_id": step_id, "action": action, "result": result})
                status = "ok" if result.get("ok") else "failed"
                agent_conversation_loop.append_event(
                    session_file,
                    {"kind": "pipeline_step_result", "step_id": step_id, "role": "system", "status": status, "summary": str(result.get("error") or action.get("type", ""))},
                )
                if not result.get("ok"):
                    raise RuntimeError(f"pipeline step failed: {step_id}: {result.get('error', '')}")
                if step_type == "package_project":
                    package_result = result
                    break
            elif step_type == "update_whiteboard":
                agent_conversation_loop.append_event(
                    session_file,
                    {
                        "kind": "whiteboard_patch_requested",
                        "role": "system",
                        "step_id": step_id,
                        "patch": step.get("patch", {}),
                        "goal": step.get("goal", ""),
                    },
                )
                agent_conversation_loop.append_event(
                    session_file,
                    {"kind": "pipeline_step_result", "step_id": step_id, "role": "system", "status": "ok", "summary": "whiteboard patch request recorded"},
                )
        if package_result:
            manifest = package_result.get("manifest", {}) if isinstance(package_result.get("manifest"), dict) else {}
            return {
                "status": str(manifest.get("status") or "ready"),
                "session_path": str(session_file),
                "project_dir": str(project),
                "manifest": manifest,
                "package_path": manifest.get("package_path", ""),
                "manifest_path": manifest.get("manifest_path", ""),
                "pipeline_manifest": pipeline_manifest,
            }
        raise RuntimeError("pipeline completed without package_project result")
    except Exception as exc:
        if fallback_to_agent_loop:
            return _fallback_to_agent_loop(
                session_file=session_file,
                project=project,
                model=model,
                timeout=timeout,
                max_turns=max_turns,
                reason=str(exc),
            )
        raise
pipeline_manifest_module = pipeline_manifest
