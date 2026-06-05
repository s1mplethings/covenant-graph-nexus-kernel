#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
from typing import Any

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_connectivity
import pipeline_manifest


PLANNER_SYSTEM_PROMPT = """You are the CGNK pipeline planner agent.
You are not the project generation agent. Your only job is to generate the pipeline_manifest JSON for this project.
Use the user messages, backend dialogue events, whiteboard, generation_context_snapshot, tool results, and delivery requirements.
Do not write project code.
Do not announce delivery completion.
Output JSON only.
The pipeline must be customized around the current project.
If the project is a web app, roles may include frontend/backend/qa.
If the project is a CLI tool, roles may include core/test/package.
If the project is an image or video tool, roles may include asset_pipeline/ui/export/qa.
Do not use a fixed template and do not over-split the work.
Every step must operate through allowed_actions.
The manifest cannot execute arbitrary Python, modify CGNK core code, call generate_project.py, call run_local_pipeline, or use simulator.
Allowed step types: agent_turn, use_skill, run_command, package_project, update_whiteboard.
Return a JSON object with kind AgentGeneratedPipelineManifest and version 1."""


def read_agent_session(session_path: str | pathlib.Path) -> list[dict[str, Any]]:
    path = pathlib.Path(session_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            events.append(doc)
    return events


def _compact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interesting = {
        "user",
        "backend_dialogue_tick",
        "generation_context_snapshot",
        "tool_result",
        "pipeline_step_result",
        "whiteboard_patch_requested",
    }
    selected: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or event.get("role") or "")
        if kind in interesting or event.get("role") == "user":
            selected.append(event)
    return selected[-80:]


def collect_generation_context(session_path: str | pathlib.Path, whiteboard: dict[str, Any] | None) -> str:
    events = read_agent_session(session_path)
    context = {
        "whiteboard": whiteboard if isinstance(whiteboard, dict) else {},
        "agent_session_events": _compact_events(events),
    }
    return json.dumps(context, ensure_ascii=False, indent=2)[-60000:]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    try:
        doc = json.loads(raw)
        return doc if isinstance(doc, dict) else None
    except Exception:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    if fenced:
        try:
            doc = json.loads(fenced.group(1))
            return doc if isinstance(doc, dict) else None
        except Exception:
            pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        try:
            doc = json.loads(match.group(0))
            return doc if isinstance(doc, dict) else None
        except Exception:
            return None
    return None


def _call_provider(prompt: str, model: str, timeout: int) -> str:
    if str(model).startswith("gpt-test"):
        raise RuntimeError("test model does not call provider")
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for pipeline planner")
    root = str(creds.get("base_url", "")).rstrip("/")
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    if check_connectivity._is_gptsapi_base_url(root):
        endpoint = root + "/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 2200}
    else:
        endpoint = root + "/responses"
        payload = {
            "model": model,
            "input": "\n".join(f"{item['role']}: {item['content']}" for item in messages),
            "temperature": 0.1,
            "max_output_tokens": 2200,
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
    raise RuntimeError(last_error or "empty planner response")


def plan_pipeline(
    session_path: str | pathlib.Path,
    whiteboard: dict[str, Any],
    model: str,
    timeout: int,
    api_budget: str = "low",
) -> dict[str, Any]:
    del api_budget
    try:
        context = collect_generation_context(session_path, whiteboard)
        raw = _call_provider(context, model, timeout)
        doc = _extract_json_object(raw)
        manifest = pipeline_manifest.normalize_pipeline_manifest(doc or {}, whiteboard)
        ok, errors = pipeline_manifest.validate_pipeline_manifest(manifest)
        if not ok:
            fallback = pipeline_manifest.default_minimal_pipeline_manifest(whiteboard)
            fallback["planner_errors"] = errors
            return fallback
        return manifest
    except Exception as exc:
        fallback = pipeline_manifest.default_minimal_pipeline_manifest(whiteboard)
        fallback["planner_fallback_reason"] = str(exc)
        return fallback
