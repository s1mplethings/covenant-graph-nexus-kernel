#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

if str(SCRIPTS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR.parent))

from cgkn.telemetry.lean import observed

import check_connectivity
import local_agent_actions


AgentCallable = Callable[[list[dict[str, Any]], str, int], str | dict[str, Any]]


SYSTEM_PROMPT = """You are the CGNK local project generation agent.
You receive the complete persisted conversation history and must improve the project through actions.
Return JSON only:
{
  "message": "short reasoning or status",
  "actions": [
    {"type": "write_file", "path": "README.md", "content": "..."},
    {"type": "read_file", "path": "README.md"},
    {"type": "list_files", "path": "."},
    {"type": "run_command", "command": "python app.py"},
    {"type": "capture_screenshot", "path": "artifacts/screenshot.txt"},
    {"type": "search_skills", "query": "test api screenshot"},
    {"type": "use_skill", "name": "patch_file", "args": {"path": "README.md", "find": "old", "replace": "new"}},
    {"type": "propose_skill", "name": "sqlite_query", "description": "...", "manifest": {}, "notes": "..."},
    {"type": "package_project", "startup_command": "python app.py", "known_limits": []},
    {"type": "final_message", "text": "What to tell the customer"}
  ]
}
Do not claim delivery is ready. Only the local package_project action can create final delivery.
Use failed tool results to repair the project before trying package_project again.
You may use search_skills to discover approved local skills.
You may use use_skill to call approved local skills.
You may use propose_skill to draft a missing skill, but draft skills are not automatically approved.
Prefer existing skills before inventing new ones.
Skill failures are tool results; inspect them and repair the project.
Do not claim delivery is ready unless package_project creates a delivery manifest.
For local web apps, prefer run_tests/http_request/browser_screenshot when useful.
For small edits, prefer patch_file over rewriting the whole file."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(session_path: pathlib.Path, event: dict[str, Any]) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    event.setdefault("created_at", now())
    with session_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_session(session_path: pathlib.Path) -> list[dict[str, Any]]:
    if not session_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in session_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            events.append(doc)
    return events


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    parse_error = ""
    try:
        doc = json.loads(raw)
        if isinstance(doc, dict):
            return doc
    except Exception as exc:
        parse_error = str(exc)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    if fenced:
        try:
            doc = json.loads(fenced.group(1))
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        try:
            doc = json.loads(match.group(0))
            if isinstance(doc, dict):
                return doc
        except Exception as exc:
            parse_error = str(exc)
    fallback = {"message": raw, "actions": _salvage_complete_write_file_actions(raw)}
    if parse_error:
        fallback["_parse_error"] = parse_error
    return fallback


def _decode_json_string_fragment(value: str) -> str:
    return json.loads(f'"{value}"')


def _salvage_complete_write_file_actions(raw: str) -> list[dict[str, Any]]:
    """Recover fully closed write_file actions from a truncated agent JSON reply."""
    actions: list[dict[str, Any]] = []
    pattern = re.compile(
        r'\{\s*"type"\s*:\s*"write_file"\s*,\s*"path"\s*:\s*"((?:\\.|[^"\\])*)"\s*,\s*"content"\s*:\s*"((?:\\.|[^"\\])*)"\s*\}',
        flags=re.S,
    )
    for match in pattern.finditer(raw):
        try:
            path = _decode_json_string_fragment(match.group(1))
            content = _decode_json_string_fragment(match.group(2))
        except Exception:
            continue
        if path.strip():
            actions.append({"type": "write_file", "path": path, "content": content})
    return actions


def parse_agent_response(response: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(response, dict):
        doc = response
    else:
        doc = _extract_json_object(str(response))
    actions = doc.get("actions", [])
    if isinstance(doc.get("action"), dict):
        actions = [doc["action"]]
    if not isinstance(actions, list):
        actions = []
    clean_actions = [action for action in actions if isinstance(action, dict)]
    result = {"message": str(doc.get("message", "")), "actions": clean_actions, "raw": response}
    if doc.get("_parse_error"):
        result["parse_error"] = str(doc.get("_parse_error"))
    return result


def _history_for_agent(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for event in events:
        kind = str(event.get("kind") or event.get("role") or "event")
        payload = json.dumps(event, ensure_ascii=False)
        lines.append(f"{kind}: {payload}")
    return "\n".join(lines)[-60000:]


def call_default_agent(events: list[dict[str, Any]], model: str, timeout: int) -> str:
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for agent conversation loop")
    root = str(creds.get("base_url", "")).rstrip("/")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _history_for_agent(events)},
    ]
    endpoint = check_connectivity._openai_compatible_endpoint(root, model=model)
    payload = check_connectivity._build_openai_compatible_payload(
        root,
        {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 6000},
    )
    transport = check_connectivity._post_json_with_retry(
        endpoint,
        payload,
        token,
        timeout,
        max_attempts=4,
        base_delay_sec=1.5,
    )
    if transport.doc is not None:
        text = check_connectivity._extract_text(transport.doc)
        if text:
            return text
    raise RuntimeError(
        f"provider_api_request_failed: {transport.error}"
        if transport.error
        else "empty agent response"
    )


def _run_action_loop(
    *, session_file, project, model, timeout, max_turns, agent, execute,
    event_context=None, read_events=None, prepare_action=None,
):
    """One owner of model turns, action dispatch, feedback and turn exhaustion.

    Manifest steps and standalone conversations retain different completion and
    repair policies. Callbacks supply context/effects, never schedule turns.
    """
    step_mode = event_context is not None
    context = event_context or {}
    turns = 0
    repair_turn_used = False
    allowed_turns = range(1, max(1, max_turns) + 1).stop - 1 if step_mode else max(1, int(max_turns))
    last_error = ""
    while turns < allowed_turns:
        turns += 1
        events = read_events() if read_events else read_session(session_file)
        try:
            response = agent(events, model, timeout)
        except Exception as exc:
            last_error = str(exc)
            append_event(session_file, {"kind": "agent_error", "role": "assistant", **context, "error": last_error, "turn": turns})
            if step_mode and getattr(exc, "outcome_unknown", False):
                return {"status": "rework_blocked", "summary": last_error,
                        "quality_audit": {"outcome_unknown": True, "requires_reconciliation": True}}
            if step_mode:
                continue
            return {"status": "failed", "error": last_error, "turns": turns, "session_path": str(session_file), "project_dir": str(project)}
        parsed = parse_agent_response(response)
        actions = parsed.get("actions", [])
        parse_error = str(parsed.get("parse_error", "")).strip() if step_mode else ""
        append_event(session_file, {
            "kind": "assistant", "role": "assistant", **context, "turn": turns,
            "message": parsed.get("message", ""), "actions": actions,
            **({"parse_error": parse_error} if step_mode else {}),
        })
        if not actions:
            last_error = f"agent returned malformed JSON: {parse_error}" if parse_error else "agent returned no actions"
            append_event(session_file, {
                "kind": "tool_result", **context, "turn": turns, "ok": False, "error": last_error,
                **({"repair_instruction": "Return strict JSON with a non-empty actions array for this same manifest step.",
                    "raw_preview": str(parsed.get("raw", ""))[:1000]} if step_mode else {}),
            })
            if step_mode:
                continue
        failed = bool(parse_error)
        if parse_error:
            last_error = f"agent response was partially recovered from malformed JSON: {parse_error}"
            append_event(session_file, {
                "kind": "tool_result", **context, "turn": turns, "ok": False, "error": last_error,
                "repair_instruction": "Some complete write_file actions were executed, but the same manifest step must return strict JSON to finish.",
                "raw_preview": str(parsed.get("raw", ""))[:1000],
            })
        package_result = None
        for action in actions:
            if prepare_action:
                action = prepare_action(action)
            action_type = str(action.get("type") or action.get("action") or "")
            append_event(session_file, {"kind": "action", **context, "turn": turns, "action": action})
            result = ({"ok": True, "type": "final_message", "text": str(action.get("text", ""))}
                      if not step_mode and action_type == "final_message" else execute(action))
            append_event(session_file, {"kind": "tool_result", **context, "turn": turns, "action": action, "result": result})
            if not result.get("ok"):
                failed = True
                if step_mode:
                    last_error = str(result.get("error") or "action failed")
            if action_type == "package_project" and result.get("ok"):
                package_result = result
                if not step_mode:
                    break
        if package_result:
            if step_mode:
                return {"status": "ok", "summary": "package_project action completed", "package_result": package_result}
            manifest = package_result.get("manifest", {}) if isinstance(package_result.get("manifest"), dict) else {}
            return {"status": str(manifest.get("status") or "ready"), "turns": turns,
                    "session_path": str(session_file), "project_dir": str(project), "manifest": manifest,
                    "package_path": manifest.get("package_path", ""), "manifest_path": manifest.get("manifest_path", "")}
        if step_mode:
            if not failed:
                return {"status": "ok", "summary": str(parsed.get("message") or "step completed")}
        elif failed and turns >= allowed_turns and not repair_turn_used:
            repair_turn_used = True
            allowed_turns += 1
            append_event(session_file, {"kind": "repair_prompt", "turn": turns,
                                       "message": "A failed action was returned to the agent for one repair attempt."})
    if step_mode:
        return {"status": "failed", "summary": last_error or "agent step failed"}
    return {"status": "max_turns_reached", "turns": turns, "session_path": str(session_file), "project_dir": str(project)}


@observed("conversation", lambda a: pathlib.Path(a["session_path"]).with_suffix(".reports"), session=lambda a:a["session_path"])
def run_agent_loop(
    *,
    session_path: str | pathlib.Path,
    project_dir: str | pathlib.Path,
    model: str = "gpt-5.4-nano",
    timeout: int = 120,
    max_turns: int = 12,
    agent: AgentCallable | None = None,
) -> dict[str, Any]:
    session_file = pathlib.Path(session_path).resolve()
    project = pathlib.Path(project_dir).resolve()
    executor = local_agent_actions.LocalAgentActionExecutor(project)
    return _run_action_loop(
        session_file=session_file, project=project, model=model, timeout=timeout,
        max_turns=max_turns, agent=agent or call_default_agent, execute=executor.execute,
    )



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the CGNK local agent conversation loop.")
    parser.add_argument("--session-path", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.4-nano"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-turns", type=int, default=12)
    args = parser.parse_args()
    result = run_agent_loop(
        session_path=args.session_path,
        project_dir=args.project_dir,
        model=args.model,
        timeout=args.timeout,
        max_turns=args.max_turns,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
